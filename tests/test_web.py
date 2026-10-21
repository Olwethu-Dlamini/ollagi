import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ollagi.budget import GIB
from ollagi.config import Config, Project
from ollagi.desktop import Settings
from ollagi.processes import Proc
from ollagi.queue import Store
from ollagi.sessions import SessionInfo
from ollagi.system import MIB, Disk, Load, Memory, Pressure

CHANGE = {"X-Ollagi": "1"}


def temp_store():
    """A queue database in a fresh temporary folder, so tests never touch the real queue."""
    return Store(Path(tempfile.mkdtemp()) / "q.db")


class FakeSessions:
    """Stands in for ollagi.sessions and remembers what the API asked it to do."""

    def __init__(self):
        self.running = {"demo": "/work/demo"}
        self.frozen = set()
        self.screens = {}
        self.sent = []

    def names(self):
        return sorted(self.running)

    def info(self, name):
        # Like the real one: a frozen session is reported from its record, without asking tmux.
        return SessionInfo(name, self.running[name], 4242, 1_000_000, True, 300 * MIB, 500 * MIB, name in self.frozen)

    def screen(self, name, lines=200, colours=False):
        return self.screens.get(name, "Claude is waiting for you")

    def start(self, name, directory, command=("claude",)):
        self.commands = getattr(self, "commands", {})
        self.commands[name] = list(command)
        if name in self.running:
            raise ValueError(f"a session called {name} is already running")
        self.running[name] = directory

    def send_text(self, name, text):
        self.sent.append(("text", name, text))

    def send_key(self, name, key):
        if key != "Enter":
            raise ValueError(f"key not allowed: {key}")
        self.sent.append(("key", name, key))

    def stop(self, name):
        del self.running[name]

    def scope_state(self, name):
        return name in self.frozen, 300 * MIB, 500 * MIB

    def freeze(self, name):
        self.frozen.add(name)

    def thaw(self, name):
        self.frozen.discard(name)


def machine(available_gib=8.0):
    return SimpleNamespace(
        memory=lambda: Memory(total=12 * GIB, available=int(available_gib * GIB), swap_total=GIB, swap_free=GIB),
        load=lambda: Load(one_minute=1.0, five_minutes=1.0, cpus=8),
        pressure=lambda: Pressure(some_avg10=0.5, some_avg60=0.2),
        disks=lambda: [Disk(mount="/", total=100 * GIB, free=40 * GIB)],
        processes=lambda: [
            Proc(pid=1, ppid=0, name="systemd", rss=10 * MIB),
            Proc(pid=200, ppid=1, name="claude", rss=380 * MIB),
            Proc(pid=300, ppid=1, name="brave", rss=600 * MIB),
        ],
        cgroup_of=lambda pid: "0::/user.slice/app.slice/app-ollagi.slice/app-ollagi-demo.slice/tmux-spawn-1.scope\n" if pid == 200 else "0::/app.slice\n",
    )


@pytest.fixture
def fake_sessions():
    return FakeSessions()


class FakeJira:
    """Invented tickets only: this repo is public."""

    def __init__(self):
        self.calls = 0

    def my_open_tickets(self):
        from ollagi.jira import Ticket

        self.calls += 1
        t = lambda key, summary: Ticket(key, summary, "To Do", (), None, "Task", f"https://j.example/browse/{key}")  # noqa: E731
        return [t("T-1", "E2E: checkout - 3 test(s) failing"), t("T-2", "E2E: search - 1 test(s) failing"),
                t("T-3", "Export the yearly report")]


def temp_notifier():
    """Phones kept in a temporary folder and a sender that records instead of sending: tests never
    reach a push service."""
    from cryptography.hazmat.primitives.asymmetric import ec

    from ollagi.notify import Notifier, Subscribers

    notifier = Notifier(Subscribers(Path(tempfile.mkdtemp()) / "push.db"), ec.generate_private_key(ec.SECP256R1()),
                        send=lambda sub, message, key, now: notifier.sent.append((sub.endpoint, message)))
    notifier.sent = []
    return notifier


def temp_outbox(helper=None):
    """An outbox with a fake slack.sh: tests never reach Slack."""
    from ollagi.slack_outbox import Outbox

    def fake(argv, stdin):
        import subprocess

        if argv[1] == "preview":
            return subprocess.CompletedProcess(argv, 0, "--- notifies: nobody\n", "")
        return subprocess.CompletedProcess(argv, 0, "posted ts=1.0", "")

    return Outbox(Path(tempfile.mkdtemp()) / "q.db", helper=Path("/fake/slack.sh"), run=helper or fake)


class FakeOutside:
    """Stands in for ollagi.outside: one invented session started in a terminal, pid 900."""

    def __init__(self, status="idle"):
        from ollagi.outside import OutsideSession

        self.session = OutsideSession(900, "conv-1", "work-12", "/work/DATA!/api", status, 1000.0, 2000.0)
        self.ended = []

    def list_sessions(self):
        return [] if self.ended else [self.session]

    def transcript_path(self, session_id):
        return Path("/nowhere.jsonl")

    def read_tail(self, path):
        return ['{"type": "user", "message": {"content": "hello"}}']

    def parse_conversation(self, lines, limit=40):
        from ollagi.outside import parse_conversation

        return parse_conversation(lines, limit=limit)

    def end_process(self, pid):
        self.ended.append(pid)
        return True


class FakeWindows:
    """Stands in for desktop.Laptop: remembers which sessions got a window on the laptop."""

    def __init__(self, desktop_running=True):
        self.desktop_running = desktop_running
        self.opened = []
        self.counted = []

    def open(self, name):
        if self.desktop_running:
            self.opened.append(name)
        return self.desktop_running

    def count(self, name):
        self.counted.append(name)
        return self.opened.count(name)

    def close(self, name):
        closed = self.opened.count(name)
        self.opened = [n for n in self.opened if n != name]
        return closed


class CatTerminals:
    """Opens `cat` in a real pty instead of `tmux attach`, and remembers what was asked for."""

    def __init__(self):
        self.opened = []

    def __call__(self, name, rows, cols):
        from ollagi.terminal import Terminal

        self.opened.append((name, rows, cols))
        return Terminal(["cat"], rows, cols)


def client(fake_sessions, available_gib=8.0, jira=None, outbox=None, outside_api=None, windows=None, terminals=None,
           summariser=None, notifier=None, **config):
    from ollagi.web import create_app

    cfg = Config(projects=(Project("simedia", "/work/DATA!"),), **config)
    app = create_app(cfg, machine=machine(available_gib), sessions_api=fake_sessions, queue_store=temp_store(),
                     notifier=notifier or temp_notifier(),
                     jira_client=jira or FakeJira(), outbox=outbox or temp_outbox(), outside_api=outside_api or FakeOutside(),
                     desktop_api=windows if windows is not None else FakeWindows(),
                     open_terminal=terminals if terminals is not None else CatTerminals(),
                     summarise=summariser or FakeSummariser())
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_the_page_and_its_files_are_served_and_nothing_else(fake_sessions):
    c = client(fake_sessions)
    assert "<title>ollagi</title>" in c.get("/").text
    for name in ("style.css", "app.js", "ansi.js", "xterm.css"):
        assert c.get(f"/static/{name}").status_code == 200
    # Loaded with import(), which a browser only accepts with a JavaScript content type.
    for name in ("xterm.mjs", "xterm-addon-fit.mjs"):
        response = c.get(f"/static/{name}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript")
    assert c.get("/static/xterm-LICENSE.txt").status_code == 404
    assert c.get("/static/..%2Fweb.py").status_code == 404
    assert c.get("/static/index.html").status_code == 404


def test_the_page_and_its_files_are_checked_for_a_new_version_every_time(fake_sessions):
    # Without this a browser guesses how long to reuse its copy: a phone kept an old app.js for
    # hours after an update and showed a new card with nothing behind it.
    c = client(fake_sessions)
    for path in ("/", "/static/app.js", "/static/style.css", "/static/ansi.js", "/manifest.webmanifest"):
        assert c.get(path).headers.get("cache-control") == "no-cache", path
    # The check is cheap: the browser sends the ETag it has and gets "not modified" back.
    etag = c.get("/static/app.js").headers["etag"]
    assert c.get("/static/app.js", headers={"If-None-Match": etag}).status_code == 304


def test_the_page_can_be_installed_as_an_app(fake_sessions):
    c = client(fake_sessions)
    assert '<link rel="manifest" href="/manifest.webmanifest">' in c.get("/").text
    response = c.get("/manifest.webmanifest")
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["start_url"] == "/" and manifest["display"] == "standalone"
    # Android asks for a 192 and a 512 pixel icon; each one listed must be served as a PNG.
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in manifest["icons"]:
        image = c.get(icon["src"])
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")


def test_the_service_worker_is_served_from_the_root_and_never_cached(fake_sessions):
    # From the root, so it covers the whole page; a worker under /static/ would only cover /static/.
    response = client(fake_sessions).get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    # The browser must ask for a new worker every time, so a change reaches the phone.
    assert response.headers["cache-control"] == "no-cache"


def test_system_reports_memory_processes_sessions_and_projects(fake_sessions):
    data = client(fake_sessions).get("/api/system").json()
    assert data["memory"]["available"] == 8 * GIB
    assert data["pressure"]["some_avg10"] == 0.5
    assert data["top_processes"][0]["name"] == "brave"
    assert data["claude_sessions"] == [{"pid": 200, "tree_rss": 380 * MIB, "processes": 1, "managed": True}]
    assert data["projects"] == [{"name": "simedia", "directory": "/work/DATA!"}]
    assert data["can_start"] >= 1


def test_sessions_are_listed_and_their_screen_is_readable(fake_sessions):
    c = client(fake_sessions)
    assert [s["name"] for s in c.get("/api/sessions").json()] == ["demo"]
    assert c.get("/api/sessions/demo/screen").json()["text"] == "Claude is waiting for you"
    assert c.get("/api/sessions").json()[0]["project"] == "demo"  # not under a configured project
    assert c.get("/api/sessions/nope/screen").status_code == 404


def test_typing_and_keys_reach_the_session(fake_sessions):
    c = client(fake_sessions)
    assert c.post("/api/sessions/demo/send", json={"text": "yes please"}, headers=CHANGE).status_code == 200
    assert c.post("/api/sessions/demo/send", json={"key": "Enter"}, headers=CHANGE).status_code == 200
    assert c.post("/api/sessions/demo/send", json={"key": "C-b"}, headers=CHANGE).status_code == 400
    assert fake_sessions.sent == [("text", "demo", "yes please"), ("key", "demo", "Enter")]


def test_start_and_stop(fake_sessions):
    c = client(fake_sessions)
    started = c.post("/api/sessions", json={"name": "sd-1", "directory": "/work/DATA!"}, headers=CHANGE)
    assert started.status_code == 200
    assert "sd-1" in fake_sessions.running
    assert c.post("/api/sessions/sd-1/stop", headers=CHANGE).status_code == 200
    assert "sd-1" not in fake_sessions.running


def test_start_is_refused_when_there_is_no_room_unless_forced(fake_sessions):
    c = client(fake_sessions, available_gib=1.0)
    refused = c.post("/api/sessions", json={"name": "sd-2", "directory": "/w"}, headers=CHANGE)
    assert refused.status_code == 409
    forced = c.post("/api/sessions", json={"name": "sd-2", "directory": "/w", "force": True}, headers=CHANGE)
    assert forced.status_code == 200


def test_changes_without_the_ollagi_header_are_refused(fake_sessions):
    response = client(fake_sessions).post("/api/sessions/demo/stop")
    assert response.status_code == 403
    assert "demo" in fake_sessions.running


def test_another_tailnet_user_is_refused(fake_sessions):
    c = client(fake_sessions, allowed_login="me@example.com")
    response = c.get("/api/system", headers={"Tailscale-User-Login": "guest@example.com"})
    assert response.status_code == 403


def test_whoami_names_the_tailscale_login_or_this_machine(fake_sessions):
    c = client(fake_sessions)
    assert c.get("/api/whoami").json() == {"login": "this machine"}
    assert c.get("/api/whoami", headers={"Tailscale-User-Login": "me@example.com"}).json() == {"login": "me@example.com"}


def test_a_frozen_session_says_so_and_refuses_typing_until_thawed(fake_sessions):
    c = client(fake_sessions)
    assert c.post("/api/sessions/demo/freeze", headers=CHANGE).status_code == 200
    assert c.get("/api/sessions/demo/screen").json()["frozen"] is True
    assert c.get("/api/sessions/demo/screen").json()["text"] is None
    assert c.post("/api/sessions/demo/send", json={"text": "hi"}, headers=CHANGE).status_code == 409
    assert c.post("/api/sessions/demo/thaw", headers=CHANGE).status_code == 200
    assert c.get("/api/sessions/demo/screen").json()["frozen"] is False


def test_watcher_state_is_reported(fake_sessions):
    data = client(fake_sessions).get("/api/watcher").json()
    assert data["level"] == "green"
    assert data["action"] == "freeze"
    assert data["events"] == []


def test_the_watcher_reads_scopes_and_freezes_through_the_sessions_module(fake_sessions):
    """Runs the server's own watcher read and act functions, as the background thread does."""
    from ollagi.web import create_app

    app = create_app(Config(), machine=machine(available_gib=0.5), sessions_api=fake_sessions, notifier=temp_notifier(), queue_store=temp_store(),
                     outbox=temp_outbox())
    w, read, act = app.state.watcher, app.state.watcher_read, app.state.watcher_act
    available, pressure, states = read()
    assert [(x.name, x.frozen) for x in states] == [("demo", False)]
    w.step(0, available, pressure, states)  # red begins
    for action in w.step(10, available, pressure, read()[2]):  # red for 10 s: act
        act(action)
    assert "demo" in fake_sessions.frozen
    assert read()[2][0].frozen


def test_qr_code_is_an_svg_of_the_phone_address(fake_sessions):
    import shutil

    from ollagi.web import create_app

    if not shutil.which("qrencode"):
        pytest.skip("qrencode not installed")
    app = create_app(Config(), machine=machine(), sessions_api=fake_sessions, notifier=temp_notifier(), phone_url="http://box.tail1.ts.net",
                     queue_store=temp_store(), outbox=temp_outbox())
    response = TestClient(app, base_url="http://127.0.0.1:8765").get("/qr.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.text.lstrip().startswith("<?xml") or "<svg" in response.text


def test_a_session_waiting_on_a_permission_shows_its_question_and_choices(fake_sessions):
    fixture = Path(__file__).parent / "fixtures" / "collie" / "claude--permission-bash.txt"
    fake_sessions.screens["demo"] = fixture.read_text()
    c = client(fake_sessions)
    listed = c.get("/api/sessions").json()[0]
    assert (listed["state"], listed["question"]) == ("needs_you", "Do you want to proceed?")
    screen = c.get("/api/sessions/demo/screen").json()
    assert [o["number"] for o in screen["options"]] == [1, 2, 3]
    assert screen["options"][2]["label"] == "No"


def test_sessions_are_grouped_under_their_configured_project(fake_sessions):
    fake_sessions.running = {"sd-1": "/work/DATA!/Admin-Api"}
    assert client(fake_sessions).get("/api/sessions").json()[0]["project"] == "simedia"


def test_tasks_are_added_listed_cancelled_and_the_queue_paused(fake_sessions, tmp_path):
    c = client(fake_sessions)
    added = c.post("/api/queue", json={"directory": str(tmp_path), "prompt": "fix it"}, headers=CHANGE).json()
    assert added["status"] == "queued"
    assert c.get("/api/queue").json()["tasks"][0]["prompt"] == "fix it"
    assert c.post(f"/api/queue/{added['id']}/cancel", headers=CHANGE).json()["status"] == "cancelled"
    assert c.post(f"/api/queue/{added['id']}/cancel", headers=CHANGE).status_code == 409
    c.post("/api/queue/pause", headers=CHANGE)
    assert c.get("/api/queue").json()["paused"] is True
    c.post("/api/queue/resume", headers=CHANGE)
    assert c.get("/api/queue").json()["paused"] is False


def test_a_task_needs_a_real_folder(fake_sessions):
    c = client(fake_sessions)
    assert c.post("/api/queue", json={"directory": "/nope", "prompt": "x"}, headers=CHANGE).status_code == 400


def test_tickets_are_grouped_and_jira_is_asked_at_most_every_five_minutes(fake_sessions):
    jira = FakeJira()
    c = client(fake_sessions, jira=jira)
    data = c.get("/api/jira/groups").json()
    assert [[t["key"] for t in g["tickets"]] for g in data["groups"]] == [["T-1", "T-2"]]
    assert [t["key"] for t in data["ungrouped"]] == ["T-3"]
    c.get("/api/jira/groups")
    assert jira.calls == 1  # served from the cache
    c.get("/api/jira/groups?refresh=true")
    assert jira.calls == 2


def test_chosen_tickets_become_one_queued_task(fake_sessions, tmp_path):
    c = client(fake_sessions)
    c.get("/api/jira/groups")
    task = c.post("/api/jira/queue", json={"keys": ["T-1", "T-2"], "directory": str(tmp_path)}, headers=CHANGE).json()
    assert task["status"] == "queued"
    assert "- T-1: E2E: checkout" in task["prompt"] and "- T-2: E2E: search" in task["prompt"]
    assert c.post("/api/jira/queue", json={"keys": ["NOPE-1"], "directory": str(tmp_path)}, headers=CHANGE).status_code == 400


def test_a_slack_draft_is_sent_only_with_its_exact_text(fake_sessions):
    c = client(fake_sessions)
    d = c.post("/api/slack/drafts", json={"channel": "#internal", "text": "hello"}, headers=CHANGE).json()
    assert c.post(f"/api/slack/drafts/{d['id']}/preview", headers=CHANGE).json() == {"notifies": "--- notifies: nobody"}
    wrong = c.post(f"/api/slack/drafts/{d['id']}/send", json={"confirmed_text": "hello!"}, headers=CHANGE)
    assert wrong.status_code == 409
    sent = c.post(f"/api/slack/drafts/{d['id']}/send", json={"confirmed_text": "hello"}, headers=CHANGE).json()
    assert sent["status"] == "sent"
    again = c.post(f"/api/slack/drafts/{d['id']}/send", json={"confirmed_text": "hello"}, headers=CHANGE)
    assert again.status_code == 409


def test_queue_events_become_drafts_only_when_a_channel_is_configured(fake_sessions):
    from ollagi.web import create_app

    box = temp_outbox()
    app = create_app(Config(slack_drafts_to="#me"), machine=machine(), sessions_api=fake_sessions, notifier=temp_notifier(),
                     queue_store=temp_store(), outbox=box)
    app.state.note_queue_event("task 3 done")
    app.state.note_queue_event("task 4 started as session q4")  # not worth a draft
    assert [(d.channel, d.text, d.status) for d in box.all()] == [("#me", "ollagi: task 3 done", "draft")]

    quiet = temp_outbox()
    app = create_app(Config(), machine=machine(), sessions_api=fake_sessions, notifier=temp_notifier(), queue_store=temp_store(), outbox=quiet)
    app.state.note_queue_event("task 3 done")
    assert quiet.all() == []


def test_sessions_started_outside_ollagi_are_listed_with_their_conversation(fake_sessions):
    c = client(fake_sessions)
    [s] = c.get("/api/outside").json()
    assert (s["name"], s["state"], s["project"]) == ("work-12", "done", "simedia")
    assert c.get("/api/outside/900/conversation").json()["items"] == [{"role": "you", "text": "hello"}]
    assert c.get("/api/outside/1/conversation").status_code == 404


def test_take_over_needs_the_exact_name_and_an_idle_session(fake_sessions):
    busy = FakeOutside(status="busy")
    c = client(fake_sessions, outside_api=busy)
    assert c.post("/api/outside/900/takeover", json={"confirm_name": "work-12"}, headers=CHANGE).status_code == 409
    assert busy.ended == []

    idle = FakeOutside()
    c = client(fake_sessions, outside_api=idle)
    assert c.post("/api/outside/900/takeover", json={"confirm_name": "work"}, headers=CHANGE).status_code == 409
    assert idle.ended == []
    done = c.post("/api/outside/900/takeover", json={"confirm_name": "work-12"}, headers=CHANGE).json()
    assert idle.ended == [900]
    assert done["session"] == "api-12"  # folder name plus the old name's ending
    assert fake_sessions.running["api-12"] == "/work/DATA!/api"
    assert fake_sessions.commands["api-12"] == ["claude", "--resume", "conv-1"]  # the same conversation


def test_a_session_started_from_the_page_also_opens_on_the_laptop(fake_sessions):
    windows = FakeWindows()
    c = client(fake_sessions, windows=windows)
    started = c.post("/api/sessions", json={"name": "sd-1", "directory": "/work/DATA!"}, headers=CHANGE).json()
    assert windows.opened == ["sd-1"]
    assert started == {"started": "sd-1", "window": True}


def test_no_window_when_opening_on_start_is_switched_off(fake_sessions):
    windows = FakeWindows()
    c = client(fake_sessions, windows=windows, desktop=Settings(open_on_start=False))
    c.post("/api/sessions", json={"name": "sd-1", "directory": "/work/DATA!"}, headers=CHANGE)
    assert windows.opened == []


def test_a_running_session_can_be_shown_on_the_desktop_when_one_is_there(fake_sessions):
    windows = FakeWindows()
    c = client(fake_sessions, windows=windows)
    assert c.post("/api/sessions/demo/desktop", headers=CHANGE).json() == {"opened": "demo"}
    assert windows.opened == ["demo"]
    assert c.post("/api/sessions/nope/desktop", headers=CHANGE).status_code == 404
    nobody_home = client(fake_sessions, windows=FakeWindows(desktop_running=False))
    assert nobody_home.post("/api/sessions/demo/desktop", headers=CHANGE).status_code == 409


def test_overnight_queue_tasks_open_no_window(fake_sessions, tmp_path):
    windows = FakeWindows()
    c = client(fake_sessions, windows=windows)
    c.post("/api/queue", json={"directory": str(tmp_path), "prompt": "fix it"}, headers=CHANGE)
    note = c.app.state.queue_runner.step(1_000)
    assert "started as session q1" in note
    assert "q1" in fake_sessions.running
    assert windows.opened == []


def test_the_button_closes_the_windows_and_the_session_keeps_running(fake_sessions):
    windows = FakeWindows()
    c = client(fake_sessions, windows=windows)
    c.post("/api/sessions/demo/desktop", headers=CHANGE)
    assert c.get("/api/sessions/demo/screen").json()["windows"] == 1
    assert c.post("/api/sessions/demo/desktop/close", headers=CHANGE).json() == {"closed": 1}
    assert c.get("/api/sessions/demo/screen").json()["windows"] == 0
    assert "demo" in fake_sessions.running
    assert c.post("/api/sessions/nope/desktop/close", headers=CHANGE).status_code == 404


def test_a_frozen_session_is_not_asked_for_its_windows(fake_sessions):
    windows = FakeWindows()
    fake_sessions.frozen.add("demo")
    c = client(fake_sessions, windows=windows)
    assert c.get("/api/sessions/demo/screen").json()["windows"] is None
    assert windows.counted == []


# The live terminal (docs/decisions/0018).

PAGE = {"origin": "http://127.0.0.1:8765"}
WS = "ws://127.0.0.1:8765/api/sessions"  # TestClient would otherwise say "testserver", an unknown host


def test_a_live_terminal_relays_typing_and_output(fake_sessions):
    import json

    terminals = CatTerminals()
    with client(fake_sessions, terminals=terminals).websocket_connect(
            f"{WS}/demo/terminal?rows=30&cols=90", headers=PAGE) as ws:
        ws.send_text(json.dumps({"type": "input", "data": "hello\n"}))
        seen = b""
        while b"hello" not in seen:
            seen += ws.receive_bytes()
    assert terminals.opened == [("demo", 30, 90)]


def refused_with(c, url, headers):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as refused:
        with c.websocket_connect(url, headers=headers):
            pass
    return refused.value.code


def test_another_website_cannot_open_a_terminal(fake_sessions):
    terminals = CatTerminals()
    c = client(fake_sessions, terminals=terminals)
    assert refused_with(c, f"{WS}/demo/terminal", {"origin": "https://evil.example"}) == 4403
    assert refused_with(c, f"{WS}/demo/terminal", {}) == 4403
    assert terminals.opened == []


def test_no_terminal_for_an_unknown_or_frozen_session_or_an_odd_size(fake_sessions):
    terminals = CatTerminals()
    c = client(fake_sessions, terminals=terminals)
    assert refused_with(c, f"{WS}/nope/terminal", PAGE) == 4404
    assert refused_with(c, f"{WS}/demo/terminal?rows=0&cols=80", PAGE) == 4400
    fake_sessions.frozen.add("demo")
    assert refused_with(c, f"{WS}/demo/terminal", PAGE) == 4409
    assert terminals.opened == []


def test_the_page_is_told_when_the_terminal_ends(fake_sessions):
    from starlette.websockets import WebSocketDisconnect

    from ollagi.terminal import Terminal

    def ending(name, rows, cols):
        return Terminal(["sh", "-c", "echo bye"], rows, cols)

    with client(fake_sessions, terminals=ending).websocket_connect(f"{WS}/demo/terminal", headers=PAGE) as ws:
        with pytest.raises(WebSocketDisconnect) as ended:
            while True:
                ws.receive_bytes()
    assert ended.value.code == 1000


# Summaries (docs/decisions/0019): a fake summariser, so no tokens are spent.

class FakeSummariser:
    def __init__(self, error=None):
        self.screens = []
        self.error = error

    def __call__(self, screen):
        from ollagi.summary import Summary

        self.screens.append(screen)
        if self.error:
            raise self.error
        return Summary("Running tests.\nWaiting for your OK.\nNext: press 1.", "claude-haiku-4-5-20251001", 600, 90, 2.2, 0.001)


def test_a_summary_is_written_from_the_screen_on_request(fake_sessions):
    fake_sessions.screens["demo"] = "42 passed\n❯ 1. Yes"
    summariser = FakeSummariser()
    data = client(fake_sessions, summariser=summariser).post("/api/sessions/demo/summary", headers=CHANGE).json()
    assert data["text"].startswith("Running tests.")
    assert (data["model"], data["input_tokens"], data["output_tokens"]) == ("claude-haiku-4-5-20251001", 600, 90)
    assert summariser.screens == ["42 passed\n❯ 1. Yes"]


def test_a_summary_spends_tokens_so_another_site_cannot_ask_for_one(fake_sessions):
    summariser = FakeSummariser()
    assert client(fake_sessions, summariser=summariser).post("/api/sessions/demo/summary").status_code == 403
    assert summariser.screens == []


def test_no_summary_for_an_unknown_or_frozen_session(fake_sessions):
    summariser = FakeSummariser()
    c = client(fake_sessions, summariser=summariser)
    assert c.post("/api/sessions/nope/summary", headers=CHANGE).status_code == 404
    fake_sessions.frozen.add("demo")
    assert c.post("/api/sessions/demo/summary", headers=CHANGE).status_code == 409
    assert summariser.screens == []


def test_one_summary_at_a_time(fake_sessions):
    summariser = FakeSummariser()
    c = client(fake_sessions, summariser=summariser)
    with c.app.state.summary_lock:  # as if another tap's summary were still being written
        response = c.post("/api/sessions/demo/summary", headers=CHANGE)
    assert response.status_code == 409
    assert "already" in response.json()["detail"]
    assert summariser.screens == []


def test_a_failed_summary_says_why(fake_sessions):
    from ollagi.summary import SummaryError

    c = client(fake_sessions, summariser=FakeSummariser(error=SummaryError("Claude AI usage limit reached")))
    response = c.post("/api/sessions/demo/summary", headers=CHANGE)
    assert response.status_code == 502
    assert "usage limit" in response.json()["detail"]


def a_subscription():
    """What a browser's pushManager.subscribe() gives the page, with keys made here."""
    from cryptography.hazmat.primitives.asymmetric import ec

    from ollagi import webpush

    key = ec.generate_private_key(ec.SECP256R1())
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/abc:123",
            "keys": {"p256dh": webpush.b64(webpush.public_bytes(key.public_key())), "auth": webpush.b64(b"0123456789abcdef")}}


def test_the_page_gets_the_server_key_and_registers_a_phone(fake_sessions):
    notifier = temp_notifier()
    c = client(fake_sessions, notifier=notifier)
    from ollagi import webpush

    state = c.get("/api/push").json()
    assert webpush.unb64(state["public_key"]) == webpush.public_bytes(notifier.key.public_key())
    assert state["phones"] == 0
    assert c.post("/api/push/subscribe", json=a_subscription(), headers=CHANGE).status_code == 200
    assert c.get("/api/push").json()["phones"] == 1
    assert c.post("/api/push/unsubscribe", json={"endpoint": a_subscription()["endpoint"]}, headers=CHANGE).json() == {"removed": True}
    assert c.get("/api/push").json()["phones"] == 0


def test_a_subscription_must_come_from_the_page_and_point_at_a_push_service(fake_sessions):
    c = client(fake_sessions)
    # Without the X-Ollagi header (another website's form, say) nothing is stored.
    assert c.post("/api/push/subscribe", json=a_subscription()).status_code == 403
    elsewhere = {**a_subscription(), "endpoint": "https://127.0.0.1:8765/api/sessions/demo/stop"}
    assert c.post("/api/push/subscribe", json=elsewhere, headers=CHANGE).status_code == 400
    assert c.get("/api/push").json()["phones"] == 0


def test_a_test_notice_goes_to_every_phone(fake_sessions):
    notifier = temp_notifier()
    c = client(fake_sessions, notifier=notifier)
    assert c.post("/api/push/test", json={}, headers=CHANGE).status_code == 409  # no phone yet
    c.post("/api/push/subscribe", json=a_subscription(), headers=CHANGE)
    assert c.post("/api/push/test", json={}, headers=CHANGE).json() == {"sent": 1, "failed": []}
    assert notifier.sent[0][1]["tag"] == "test"


def test_queue_events_and_watcher_actions_are_handed_to_the_notifier(fake_sessions):
    from ollagi.watcher import Action

    notifier = temp_notifier()
    c = client(fake_sessions, notifier=notifier)
    c.app.state.note_queue_event("task 4 started as session q4")
    c.app.state.note_queue_event("task 4 done")
    c.app.state.watcher_act(Action("freeze", "demo"))
    waiting = []
    while not notifier.outbox.empty():
        waiting.append(notifier.outbox.get())
    assert [(n.title, n.body) for n in waiting] == [("Queue", "task 4 done"), ("Memory low", "Paused demo to free memory.")]


def test_the_server_reads_session_states_for_the_notifier(fake_sessions):
    fake_sessions.screens["demo"] = "\n".join(["Do you want to make this edit?", "❯ 1. Yes", "  2. No"])
    c = client(fake_sessions)
    assert c.app.state.read_states() == {"demo": ("needs_you", "Do you want to make this edit?")}
    fake_sessions.freeze("demo")
    assert c.app.state.read_states() == {"demo": ("frozen", None)}
