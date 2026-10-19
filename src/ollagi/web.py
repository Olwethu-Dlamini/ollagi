"""The web server: one page (static/index.html) plus a small JSON API it calls.

    GET  /                              the page
    GET  /api/system                    memory, pressure, load, disks, heavy processes, Claude sessions
    GET  /api/sessions                  ollagi sessions with their state and memory
    GET  /api/sessions/{name}/screen    the end of a session's screen, as text
    POST /api/sessions                  start a session   {"name", "directory", "force"}
    POST /api/sessions/{name}/send      type into it      {"text"} or {"key"}
    POST /api/sessions/{name}/stop      stop it
    POST /api/sessions/{name}/freeze    pause it (nothing lost)
    POST /api/sessions/{name}/thaw      continue it
    GET  /api/watcher                   the RAM watcher's level, setting and recent events
    GET  /qr.svg                        the phone address as a QR code

`create_app` receives the machine readers and the sessions module as arguments. The real server
passes the real ones; tests pass fakes, so the API is tested without touching this laptop.
"""

import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from ollagi import access, sessions, system, watcher as watching
from ollagi.budget import Limits, how_many_can_start
from ollagi.config import Config
from ollagi.processes import find_sessions, read_processes

STATIC = Path(__file__).parent / "static"


def real_machine() -> SimpleNamespace:
    return SimpleNamespace(
        memory=system.read_memory,
        load=system.read_load,
        pressure=system.read_pressure,
        disks=system.read_disks,
        processes=read_processes,
        cgroup_of=lambda pid: Path(f"/proc/{pid}/cgroup").read_text(),
    )


class StartRequest(BaseModel):
    name: str
    directory: str
    force: bool = False


class SendRequest(BaseModel):
    text: str | None = None
    key: str | None = None


def create_app(config: Config, machine=None, sessions_api=sessions, run_watcher=False, phone_url=None) -> FastAPI:
    machine = machine or real_machine()
    watcher = watching.Watcher(config.watcher)

    def read_for_watcher():
        """What the watcher needs, read without asking tmux (a frozen session's tmux cannot answer)."""
        states = []
        for name in sessions_api.names():
            frozen, current, _peak = sessions_api.scope_state(name)
            states.append(watching.SessionState(name, current or 0, frozen))
        pressure = machine.pressure()
        return machine.memory().available, pressure.some_avg10 if pressure else 0.0, states

    def act_for_watcher(action: watching.Action) -> None:
        {"freeze": sessions_api.freeze, "thaw": sessions_api.thaw, "stop": sessions_api.stop}[action.kind](action.name)

    @asynccontextmanager
    async def lifespan(app):
        # The watcher runs in a background thread for as long as the server runs.
        stop = threading.Event()
        if run_watcher:
            threading.Thread(
                target=watching.run_forever, args=(watcher, read_for_watcher, act_for_watcher, stop), daemon=True
            ).start()
        yield
        stop.set()

    app = FastAPI(title="ollagi", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.watcher = watcher
    # Kept on the app so tests can drive exactly what the background thread runs.
    app.state.watcher_read = read_for_watcher
    app.state.watcher_act = act_for_watcher

    @app.middleware("http")
    async def check_access(request: Request, call_next):
        decision = access.check(
            request.method, dict(request.headers), config.allowed_login, config.allowed_hosts
        )
        if not decision.allowed:
            return JSONResponse({"error": decision.reason}, status_code=403)
        return await call_next(request)

    def verdict(memory, load, claude_sessions):
        return how_many_can_start(memory, load, [s.tree_rss for s in claude_sessions], Limits())

    @app.get("/")
    def page():
        return FileResponse(STATIC / "index.html")

    @app.get("/qr.svg")
    def qr_code():
        if not phone_url:
            raise HTTPException(404, "no phone address: Tailscale is not running")
        svg = subprocess.run(["qrencode", "-t", "SVG", "-m", "2", "-o", "-", phone_url], capture_output=True, timeout=10)
        if svg.returncode != 0:
            raise HTTPException(500, "qrencode failed")
        return Response(svg.stdout, media_type="image/svg+xml")

    @app.get("/api/watcher")
    def watcher_state():
        s = watcher.settings
        return {
            "level": watcher.level,
            "action": s.action,
            "frozen_by_watcher": list(watcher.frozen_by_me),
            "thresholds": {"amber_free": s.amber_free, "red_free": s.red_free,
                           "amber_pressure": s.amber_pressure, "red_pressure": s.red_pressure},
            "events": [{"time": e.time, "text": e.text} for e in list(watcher.events)[-20:]],
            "phone_url": phone_url,
        }

    @app.get("/api/whoami")
    def whoami(request: Request):
        """Who this request comes from: a Tailscale login, or "this machine" for local requests."""
        return {"login": request.headers.get("tailscale-user-login") or "this machine"}

    @app.get("/api/system")
    def system_state():
        memory, load, procs = machine.memory(), machine.load(), machine.processes()
        claude_sessions = find_sessions(procs)
        pressure = machine.pressure()
        result = verdict(memory, load, claude_sessions)
        return {
            "memory": {"total": memory.total, "available": memory.available},
            "swap": {"total": memory.swap_total, "used": memory.swap_total - memory.swap_free},
            "load": asdict(load),
            "pressure": asdict(pressure) if pressure else None,
            "disks": [asdict(d) for d in machine.disks()],
            "can_start": result.can_start,
            "reason": result.reason,
            "top_processes": [
                {"pid": p.pid, "name": p.name, "rss": p.rss}
                for p in sorted(procs, key=lambda p: p.rss, reverse=True)[:8]
            ],
            "claude_sessions": [
                {**asdict(s), "managed": _is_managed(machine, s.pid)} for s in claude_sessions
            ],
            "projects": [asdict(p) for p in config.projects],
        }

    @app.get("/api/sessions")
    def list_sessions():
        now = time.time()
        found = []
        for name in sessions_api.names():
            info = sessions_api.info(name)
            found.append({**asdict(info), "age_seconds": int(now - info.created)})
        return found

    @app.get("/api/sessions/{name}/screen")
    def screen(name: str, lines: int = 200):
        _require_session(sessions_api, name)
        _refuse_if_frozen(sessions_api, name)
        return {"name": name, "text": sessions_api.screen(name, lines=min(max(lines, 10), 2000))}

    @app.post("/api/sessions")
    def start_session(body: StartRequest):
        if not body.force:
            memory, load = machine.memory(), machine.load()
            result = verdict(memory, load, find_sessions(machine.processes()))
            if not result.can_start:
                raise HTTPException(409, f"no room for another session: {result.reason}")
        try:
            sessions_api.start(body.name, body.directory)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(500, str(error)) from error
        return {"started": body.name}

    @app.post("/api/sessions/{name}/send")
    def send(name: str, body: SendRequest):
        _require_session(sessions_api, name)
        _refuse_if_frozen(sessions_api, name)
        try:
            if body.key:
                sessions_api.send_key(name, body.key)
            elif body.text is not None:
                sessions_api.send_text(name, body.text)
            else:
                raise HTTPException(400, "send needs text or a key")
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"sent": True}

    @app.post("/api/sessions/{name}/stop")
    def stop(name: str):
        _require_session(sessions_api, name)
        sessions_api.stop(name)
        return {"stopped": name}

    @app.post("/api/sessions/{name}/freeze")
    def freeze(name: str):
        _require_session(sessions_api, name)
        sessions_api.freeze(name)
        return {"frozen": name}

    @app.post("/api/sessions/{name}/thaw")
    def thaw(name: str):
        _require_session(sessions_api, name)
        sessions_api.thaw(name)
        return {"thawed": name}

    return app


def _refuse_if_frozen(sessions_api, name: str) -> None:
    if sessions_api.scope_state(name)[0]:
        raise HTTPException(409, f"{name} is frozen; resume it to see or type into it")


def _require_session(sessions_api, name: str) -> None:
    try:
        known = name in sessions_api.names()
    except ValueError:
        known = False
    if not known:
        raise HTTPException(404, f"no session called {name}")


def _is_managed(machine, pid: int) -> bool:
    """True when the process runs inside one of ollagi's session slices."""
    try:
        return "/app-ollagi.slice/" in machine.cgroup_of(pid)
    except OSError:
        return False
