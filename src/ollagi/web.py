"""The web server: one page (static/index.html) plus a small JSON API it calls.

    GET  /                              the page
    GET  /api/system                    memory, pressure, load, disks, heavy processes, Claude sessions
    GET  /api/sessions                  ollagi sessions with their state and memory
    GET  /api/sessions/{name}/screen    the end of a session's screen, as text
    POST /api/sessions                  start a session   {"name", "directory", "force", "program": "claude" | "shell"}
    POST /api/sessions/{name}/send      type into it      {"text"} or {"key"}
    POST /api/sessions/{name}/answer    press a menu key, only if that question is still on screen {"key", "question"}
    POST /api/sessions/{name}/stop      stop it
    POST /api/sessions/{name}/summary   a short summary of its screen, written by Haiku (spends tokens)
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
    GET  /api/outside                   Claude sessions started outside ollagi (from Claude's own files)
    GET  /api/outside/{pid}/conversation   that session's recent conversation, read only
    POST /api/outside/{pid}/takeover    end it in its window, reopen it in ollagi {"confirm_name"}
    GET  /api/slack/drafts              the Slack outbox
    POST /api/slack/drafts              add a draft       {"channel", "text", "thread_ts"}
    POST /api/slack/drafts/{id}/edit | /preview | /discard
    POST /api/slack/drafts/{id}/send    send ONE draft    {"confirmed_text"}, which must equal its text
    GET  /api/push                      notifications: the server's public key, phones, recent events
    POST /api/push/subscribe            register this phone's browser   {"endpoint", "keys"}
    POST /api/push/unsubscribe          forget it                       {"endpoint"}
    POST /api/push/test                 send a test notification to every phone
    GET  /qr.svg                        the phone address as a QR code
    GET  /manifest.webmanifest          what a phone needs to install the page as an app
    GET  /sw.js                         the service worker (installing, and notifications)
    WS   /api/sessions/{name}/terminal  a live terminal for the session (?rows=&cols=)

`create_app` receives the machine readers and the sessions module as arguments. The real server
passes the real ones; tests pass fakes, so the API is tested without touching this laptop.
"""

import secrets
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from collections import deque

from ollagi import (access, claude_screen, desktop, grouping, notify, outside, queue as queueing, sessions, slack_outbox,
                    summary, system, terminal, watcher as watching, webpush)
from ollagi.budget import Limits, how_many_can_start
from ollagi.config import Config
from ollagi.processes import find_sessions, read_processes

STATIC = Path(__file__).parent / "static"
# The page's own files: the browser asks each time whether its copy is still current (a cheap
# "304 not modified" when it is). Without this it guesses, and kept an old app.js for hours.
NO_CACHE = {"Cache-Control": "no-cache"}


def page_file(request: Request, path: Path, media_type: str | None = None) -> Response:
    """One of the page's files, or "304 not modified" when the browser already has this version.
    The ETag names the version: the file's change time and size."""
    stat = path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    headers = {**NO_CACHE, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=media_type, headers=headers)


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
    name: str = ""  # empty: named after the folder, like `ollagi here` (docs/decisions/0030)
    directory: str
    force: bool = False
    program: str = "claude"  # or "shell": a plain terminal in the folder (docs/decisions/0027)


class SendRequest(BaseModel):
    text: str | None = None
    key: str | None = None


class AnswerRequest(BaseModel):
    key: str
    question: str


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


class TakeoverRequest(BaseModel):
    confirm_name: str


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys


class UnsubscribeRequest(BaseModel):
    endpoint: str

# Claude Code's own status words for a session, as the page's state dots.
OUTSIDE_STATE = {"busy": "working", "waiting": "needs_you", "idle": "done"}

# Queue events worth a Slack draft, when [slack] drafts_to is set (never sent without me).
DRAFT_WORTHY = (" done", "waiting for you", "usage limit", "failed")


def create_app(config: Config, machine=None, sessions_api=sessions, run_watcher=False, phone_url=None,
               queue_store=None, run_queue=False, command_for=None, results_dir=None, jira_client=None,
               outbox=None, outside_api=outside, desktop_api=None, open_terminal=None, summarise=None,
               notifier=None, run_notifier=False) -> FastAPI:
    machine = machine or real_machine()
    # Windows on this laptop for a session (docs/decisions/0017). Only the page's Start and the
    # open/close button use them; the overnight queue never opens one.
    laptop = desktop_api or desktop.Laptop(config.desktop)
    # A live terminal in the browser (docs/decisions/0018): `tmux attach` in a pty. Tests pass `cat`.
    open_terminal = open_terminal or (lambda name, rows, cols: terminal.Terminal(terminal.session_command(name), rows, cols))
    # Summaries (docs/decisions/0019) run `claude -p`; tests pass a fake that spends nothing.
    summarise = summarise or summary.summarise
    # One at a time: a double tap must not pay twice, and each run is a claude process of its own.
    summary_lock = threading.Lock()
    watcher = watching.Watcher(config.watcher)
    store = queue_store or queueing.Store()
    drafts = outbox or slack_outbox.Outbox()
    queue_events: deque = deque(maxlen=50)
    # Notifications on the phone (docs/decisions/0024). Tests pass one that never sends.
    notifier = notifier or notify.Notifier(notify.Subscribers(), webpush.load_or_create_key(notify.DEFAULT_KEY))

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
        notifier.notify(notify.queue_notice(text))

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
        notifier.notify(notify.watcher_notice(action.kind, action.name))

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
        if run_notifier:
            threading.Thread(target=notify.run_sender, args=(notifier, stop), daemon=True).start()
            threading.Thread(target=notify.watch_sessions, args=(read_states, notifier, stop), daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="ollagi", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.watcher = watcher
    # Kept on the app so tests can drive exactly what the background thread runs.
    app.state.watcher_read = read_for_watcher
    app.state.watcher_act = act_for_watcher
    app.state.queue_runner = runner
    app.state.note_queue_event = note_queue_event
    app.state.summary_lock = summary_lock
    app.state.notifier = notifier

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
    def page(request: Request):
        return page_file(request, STATIC / "index.html")

    @app.get("/static/{name}")
    def static_file(name: str, request: Request):
        """The page's own files. Only these names are served, so no other file can be reached."""
        if name not in {"style.css", "app.js", "ansi.js", "xterm.mjs", "xterm-addon-fit.mjs", "xterm-addon-webgl.mjs",
                        "xterm.css", "icon-192.png", "icon-512.png"}:
            raise HTTPException(404, "no such file")
        return page_file(request, STATIC / name)

    @app.get("/manifest.webmanifest")
    def manifest(request: Request):
        """Name, icons and look of the installed app (docs/decisions/0023)."""
        return page_file(request, STATIC / "manifest.webmanifest", "application/manifest+json")

    @app.get("/sw.js")
    def service_worker(request: Request):
        # Served from the root, so it covers every page of the site. no-cache: the browser checks
        # for a new version each time instead of keeping an old one for up to a day.
        return page_file(request, STATIC / "sw.js", "text/javascript")

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

    def read_states() -> dict[str, tuple[str, str | None]]:
        """Every Claude session's state, question and choices, as the page shows them; the notifier
        reads this. A shell session is left out: it never needs me, and a program in it could draw
        something that looks like a Claude menu."""
        found = {}
        for name in sessions_api.names():
            info = sessions_api.info(name)
            if info.program != "claude":
                continue
            reading = state_of(name, info)
            found[name] = (reading.state, reading.question, tuple(reading.options))
        return found

    app.state.read_states = read_states

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
            # Its windows are not counted either: a paused tmux would not answer.
            return {"name": name, "frozen": True, "text": None, "state": "frozen", "question": None, "options": [],
                    "windows": None}
        text = sessions_api.screen(name, lines=min(max(lines, 10), 2000), colours=True)
        reading = claude_screen.read(text)
        return {
            "name": name, "frozen": False, "text": text, "state": reading.state,
            "question": reading.question, "options": [asdict(o) for o in reading.options],
            "windows": laptop.count(name),
        }

    @app.post("/api/sessions")
    def start_session(body: StartRequest):
        if body.program not in ("claude", "shell"):
            raise HTTPException(400, "program must be \"claude\" or \"shell\"")
        # A shell is a few MiB and is not a Claude session, so the budget (made for Claude's 1.5 GiB)
        # does not apply to it.
        if body.program == "claude" and not body.force:
            memory, load = machine.memory(), machine.load()
            result = verdict(memory, load, find_sessions(machine.processes()))
            if not result.can_start:
                raise HTTPException(409, f"no room for another session: {result.reason}")
        command = ["claude"] if body.program == "claude" else [sessions.login_shell()]
        name = body.name.strip() or sessions.name_for(body.directory, sessions_api.names(), secrets.token_hex(2))
        try:
            sessions_api.start(name, body.directory, command)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(500, str(error)) from error
        window = laptop.open(name) if config.desktop.open_on_start else False
        return {"started": name, "window": window}

    @app.post("/api/sessions/{name}/desktop")
    def show_on_desktop(name: str):
        _require_session(sessions_api, name)
        if not laptop.open(name):
            raise HTTPException(409, "no desktop is running on the laptop to show it on")
        return {"opened": name}

    @app.post("/api/sessions/{name}/desktop/close")
    def close_on_desktop(name: str):
        _require_session(sessions_api, name)
        return {"closed": laptop.close(name)}

    @app.websocket("/api/sessions/{name}/terminal")
    async def live_terminal(websocket: WebSocket, name: str, rows: int = 24, cols: int = 80):
        # The access middleware above sees HTTP requests only, so a WebSocket is checked here.
        # Refusing before accepting answers the browser with an error instead of opening anything;
        # the 44xx codes mirror HTTP's 403, 404, 400 and 409.
        decision = access.check_terminal(dict(websocket.headers), config.allowed_login, config.allowed_hosts)
        if not decision.allowed:
            return await websocket.close(code=4403, reason=decision.reason)
        try:
            known = name in sessions_api.names()
        except ValueError:
            known = False
        if not known:
            return await websocket.close(code=4404, reason=f"no session called {name}")
        if not terminal.valid_size(rows, cols):
            return await websocket.close(code=4400, reason="terminal size out of range")
        if sessions_api.scope_state(name)[0]:
            return await websocket.close(code=4409, reason=f"{name} is frozen; resume it first")
        await websocket.accept()
        await terminal.relay(websocket, open_terminal(name, rows, cols),
                             to_bottom=lambda: sessions_api.leave_scrollback(name))

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

    @app.post("/api/sessions/{name}/answer")
    def answer(name: str, body: AnswerRequest):
        """A button on a notification (docs/decisions/0029). The notification may be minutes old, so
        the key is pressed only if the same question with that choice is still on the screen;
        otherwise nothing is typed and the answer is 409."""
        _require_session(sessions_api, name)
        _refuse_if_frozen(sessions_api, name)
        reading = claude_screen.read(sessions_api.screen(name, lines=80))
        if reading.state != "needs_you" or reading.question != body.question:
            raise HTTPException(409, f"{name} is no longer asking that; open ollagi to see its screen")
        if body.key not in {str(o.number) for o in reading.options}:
            raise HTTPException(409, f"{name} no longer offers choice {body.key}; open ollagi to see its screen")
        sessions_api.send_key(name, body.key)
        return {"answered": body.key}

    @app.post("/api/sessions/{name}/summary")
    def summarise_session(name: str):
        # A POST, so the X-Ollagi rule applies: another website cannot spend my tokens.
        _require_session(sessions_api, name)
        _refuse_if_frozen(sessions_api, name)
        if not summary_lock.acquire(blocking=False):
            raise HTTPException(409, "a summary is already being written; wait for it")
        try:
            return asdict(summarise(sessions_api.screen(name, lines=200)))
        except summary.SummaryError as error:
            raise HTTPException(502, str(error)) from error
        finally:
            summary_lock.release()

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

    def outside_sessions():
        managed = {s.pid for s in find_sessions(machine.processes()) if _is_managed(machine, s.pid)}
        memory = {s.pid: s.tree_rss for s in find_sessions(machine.processes())}
        return [s for s in outside_api.list_sessions() if s.pid not in managed], memory

    @app.get("/api/outside")
    def list_outside():
        found, memory = outside_sessions()
        now = time.time()
        return [{**asdict(s), "state": OUTSIDE_STATE.get(s.status, "unknown"), "project": project_of(s.cwd),
                 "memory": memory.get(s.pid), "age_seconds": int(now - s.started)} for s in found]

    def find_outside(pid: int):
        found, _ = outside_sessions()
        match = next((s for s in found if s.pid == pid), None)
        if match is None:
            raise HTTPException(404, f"no Claude session with pid {pid} outside ollagi")
        return match

    @app.get("/api/outside/{pid}/conversation")
    def outside_conversation(pid: int):
        s = find_outside(pid)
        path = outside_api.transcript_path(s.session_id)
        if path is None:
            return {"title": None, "items": []}
        title, items = outside_api.parse_conversation(outside_api.read_tail(path))
        return {"title": title, "items": [asdict(i) for i in items]}

    @app.post("/api/outside/{pid}/takeover")
    def take_over(pid: int, body: TakeoverRequest):
        s = find_outside(pid)
        if body.confirm_name != s.name:
            raise HTTPException(409, "the typed name does not match; nothing was changed")
        if s.status != "idle":
            raise HTTPException(409, f"{s.name} is {s.status}; only an idle session can be taken over")
        new_name = sessions.name_for(s.cwd, sessions_api.names(), s.name.rsplit("-", 1)[-1])
        if not outside_api.end_process(s.pid):
            raise HTTPException(500, f"{s.name} did not end within 10 s; nothing was reopened")
        try:
            sessions_api.start(new_name, s.cwd, ["claude", "--resume", s.session_id])
        except (ValueError, RuntimeError) as error:
            raise HTTPException(500, f"{s.name} ended, but reopening failed: {error}. "
                                     f"Reopen it by hand: cd '{s.cwd}' && claude --resume {s.session_id}") from error
        return {"session": new_name, "attach": f"tmux -L ollagi-{new_name} attach"}

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

    @app.get("/api/push")
    def push_state():
        return {
            "public_key": webpush.b64(webpush.public_bytes(notifier.key.public_key())),
            "phones": len(notifier.subscribers.all()),
            "events": list(notifier.events)[-10:],
        }

    @app.post("/api/push/subscribe")
    def push_subscribe(body: SubscribeRequest):
        try:
            notifier.subscribers.add(webpush.Subscription(body.endpoint, body.keys.p256dh, body.keys.auth))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"subscribed": True}

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe(body: UnsubscribeRequest):
        return {"removed": notifier.subscribers.remove(body.endpoint)}

    @app.post("/api/push/test")
    def push_test():
        if not notifier.subscribers.all():
            raise HTTPException(409, "no phone has turned notifications on yet")
        return notifier.deliver(notify.Notice("ollagi", "Notifications work on this phone.", "test", "/"))

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
