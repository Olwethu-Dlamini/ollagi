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
    GET  /api/queue                     the overnight queue: tasks, paused or not, recent events
    POST /api/queue                     add a task        {"directory", "prompt"}
    POST /api/queue/{id}/cancel         cancel a queued task
    POST /api/queue/pause | /resume     hold or release the queue
    GET  /api/queue/{id}/result         a finished task's final screen, as text
    GET  /api/jira/groups               my open Jira tickets, grouped (read only, cached 5 minutes)
    POST /api/jira/queue                queue chosen tickets as one task {"keys", "directory"}
    GET  /api/slack/drafts              the Slack outbox
    POST /api/slack/drafts              add a draft       {"channel", "text", "thread_ts"}
    POST /api/slack/drafts/{id}/edit | /preview | /discard
    POST /api/slack/drafts/{id}/send    send ONE draft    {"confirmed_text"}, which must equal its text
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

from collections import deque

from ollagi import access, claude_screen, grouping, queue as queueing, sessions, slack_outbox, system, watcher as watching
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


class TaskRequest(BaseModel):
    directory: str
    prompt: str


class TicketsRequest(BaseModel):
    keys: list[str]
    directory: str

JIRA_CACHE_SECONDS = 300


class DraftRequest(BaseModel):
    channel: str
    text: str
    thread_ts: str | None = None


class EditRequest(BaseModel):
    text: str


class SendDraftRequest(BaseModel):
    confirmed_text: str

# Queue events worth a Slack draft, when [slack] drafts_to is set (never sent without me).
DRAFT_WORTHY = (" done", "waiting for you", "usage limit", "failed")


def create_app(config: Config, machine=None, sessions_api=sessions, run_watcher=False, phone_url=None,
               queue_store=None, run_queue=False, command_for=None, results_dir=None, jira_client=None,
               outbox=None) -> FastAPI:
    machine = machine or real_machine()
    watcher = watching.Watcher(config.watcher)
    store = queue_store or queueing.Store()
    drafts = outbox or slack_outbox.Outbox()
    queue_events: deque = deque(maxlen=50)

    def room_for_a_task() -> bool:
        """The queue may start a task only when the budget says one fits and the watcher is green."""
        if watcher.level != "green":
            return False
        result = how_many_can_start(machine.memory(), machine.load(),
                                    [s.tree_rss for s in find_sessions(machine.processes())], Limits())
        return result.can_start > 0

    def note_queue_event(text: str) -> None:
        queue_events.append({"time": time.time(), "text": text})
        if config.slack_drafts_to and any(word in text for word in DRAFT_WORTHY):
            drafts.add(config.slack_drafts_to, f"ollagi: {text}", source="queue")

    runner = queueing.Runner(store, sessions_api, room=room_for_a_task,
                             **({"command_for": command_for} if command_for else {}),
                             **({"results_dir": results_dir} if results_dir else {}))

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
        if run_queue:
            threading.Thread(target=queueing.run_forever, args=(runner, note_queue_event, stop), daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="ollagi", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.watcher = watcher
    # Kept on the app so tests can drive exactly what the background thread runs.
    app.state.watcher_read = read_for_watcher
    app.state.watcher_act = act_for_watcher
    app.state.queue_runner = runner
    app.state.note_queue_event = note_queue_event

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

    @app.get("/static/{name}")
    def static_file(name: str):
        """The page's own files. Only these names are served, so no other file can be reached."""
        if name not in {"style.css", "app.js", "ansi.js"}:
            raise HTTPException(404, "no such file")
        return FileResponse(STATIC / name)

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

    def project_of(directory: str) -> str:
        """The configured project a folder belongs to, else the folder's own name."""
        for project in config.projects:
            if directory == project.directory or directory.startswith(project.directory.rstrip("/") + "/"):
                return project.name
        return Path(directory).name or directory

    def state_of(name: str, info) -> claude_screen.Reading:
        if info.frozen:
            return claude_screen.Reading("frozen")
        if not info.alive:
            return claude_screen.Reading("exited")
        return claude_screen.read(sessions_api.screen(name, lines=80))

    @app.get("/api/sessions")
    def list_sessions():
        now = time.time()
        found = []
        for name in sessions_api.names():
            info = sessions_api.info(name)
            reading = state_of(name, info)
            found.append({
                **asdict(info),
                "age_seconds": int(now - info.created),
                "project": project_of(info.directory),
                "state": reading.state,
                "question": reading.question,
            })
        return found

    @app.get("/api/sessions/{name}/screen")
    def screen(name: str, lines: int = 200):
        _require_session(sessions_api, name)
        if sessions_api.scope_state(name)[0]:
            # Not an error: the session is fine, its tmux is just paused and cannot draw the screen.
            return {"name": name, "frozen": True, "text": None, "state": "frozen", "question": None, "options": []}
        text = sessions_api.screen(name, lines=min(max(lines, 10), 2000), colours=True)
        reading = claude_screen.read(text)
        return {
            "name": name, "frozen": False, "text": text, "state": reading.state,
            "question": reading.question, "options": [asdict(o) for o in reading.options],
        }

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

    @app.get("/api/queue")
    def queue_state():
        return {
            "paused": store.paused(),
            "pause_reason": store.pause_reason(),
            "tasks": [{**asdict(t), "project": project_of(t.directory)} for t in reversed(store.all())],
            "events": list(queue_events)[-20:],
        }

    @app.post("/api/queue")
    def add_task(body: TaskRequest):
        try:
            return asdict(store.add(body.directory, body.prompt))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/queue/{task_id}/cancel")
    def cancel_task(task_id: int):
        try:
            return asdict(store.cancel(task_id))
        except KeyError as error:
            raise HTTPException(404, f"no task {task_id}") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/queue/pause")
    def pause_queue():
        store.set_paused(True, "paused by hand")
        return {"paused": True}

    @app.post("/api/queue/resume")
    def resume_queue():
        store.set_paused(False)
        return {"paused": False}

    @app.get("/api/queue/{task_id}/result")
    def task_result(task_id: int):
        path = runner.results_dir / f"task-{task_id}.txt"
        if not path.exists():
            raise HTTPException(404, f"no saved result for task {task_id}")
        return {"id": task_id, "text": path.read_text()}

    jira_cache = {"time": 0.0, "tickets": []}

    def my_tickets(refresh: bool = False):
        """Open tickets, read from Jira at most every 5 minutes unless a refresh is asked for."""
        if refresh or time.time() - jira_cache["time"] > JIRA_CACHE_SECONDS:
            from ollagi.jira import Jira

            client = jira_client or Jira()
            jira_cache.update(time=time.time(), tickets=client.my_open_tickets())
        return jira_cache["tickets"]

    @app.get("/api/jira/groups")
    def jira_groups(refresh: bool = False):
        try:
            tickets = my_tickets(refresh)
        except (OSError, KeyError, ValueError) as error:  # no ~/.jira.env, no network, a bad answer
            raise HTTPException(502, f"could not read Jira: {error}") from error
        groups = grouping.group(tickets)
        grouped = {t.key for g in groups for t in g.tickets}
        return {
            "read_at": jira_cache["time"],
            "tickets": len(tickets),
            "groups": [{"reason": g.reason, "tickets": [asdict(t) for t in g.tickets]} for g in groups],
            "ungrouped": [asdict(t) for t in tickets if t.key not in grouped],
        }

    @app.post("/api/jira/queue")
    def queue_tickets(body: TicketsRequest):
        by_key = {t.key: t for t in my_tickets()}
        chosen = [by_key[k] for k in body.keys if k in by_key]
        if not chosen:
            raise HTTPException(400, "none of those tickets are in my open tickets")
        try:
            return asdict(store.add(body.directory, grouping.prompt_for(chosen)))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/slack/drafts")
    def list_drafts():
        return {"drafts_to": config.slack_drafts_to, "drafts": [asdict(d) for d in drafts.all()]}

    @app.post("/api/slack/drafts")
    def add_draft(body: DraftRequest):
        try:
            return asdict(drafts.add(body.channel, body.text, body.thread_ts))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def draft_action(draft_id: int, action):
        try:
            return action()
        except KeyError as error:
            raise HTTPException(404, f"no draft {draft_id}") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            raise HTTPException(502, str(error)) from error

    @app.post("/api/slack/drafts/{draft_id}/edit")
    def edit_draft(draft_id: int, body: EditRequest):
        return draft_action(draft_id, lambda: asdict(drafts.edit(draft_id, body.text)))

    @app.post("/api/slack/drafts/{draft_id}/preview")
    def preview_draft(draft_id: int):
        return draft_action(draft_id, lambda: {"notifies": drafts.preview(draft_id)})

    @app.post("/api/slack/drafts/{draft_id}/discard")
    def discard_draft(draft_id: int):
        return draft_action(draft_id, lambda: asdict(drafts.discard(draft_id)))

    @app.post("/api/slack/drafts/{draft_id}/send")
    def send_draft(draft_id: int, body: SendDraftRequest):
        return draft_action(draft_id, lambda: asdict(drafts.send(draft_id, body.confirmed_text)))

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
