import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ollagi.budget import GIB
from ollagi.config import Config, Project
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
        return SessionInfo(name, self.running[name], 4242, 1_000_000, True, 300 * MIB, 500 * MIB)

    def screen(self, name, lines=200, colours=False):
        return self.screens.get(name, "Claude is waiting for you")

    def start(self, name, directory):
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


def client(fake_sessions, available_gib=8.0, jira=None, **config):
    from ollagi.web import create_app

    cfg = Config(projects=(Project("simedia", "/work/DATA!"),), **config)
    app = create_app(cfg, machine=machine(available_gib), sessions_api=fake_sessions, queue_store=temp_store(),
                     jira_client=jira or FakeJira())
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_the_page_and_its_three_files_are_served_and_nothing_else(fake_sessions):
    c = client(fake_sessions)
    assert "<title>ollagi</title>" in c.get("/").text
    for name in ("style.css", "app.js", "ansi.js"):
        assert c.get(f"/static/{name}").status_code == 200
    assert c.get("/static/..%2Fweb.py").status_code == 404
    assert c.get("/static/index.html").status_code == 404


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

    app = create_app(Config(), machine=machine(available_gib=0.5), sessions_api=fake_sessions, queue_store=temp_store())
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
    app = create_app(Config(), machine=machine(), sessions_api=fake_sessions, phone_url="http://box.tail1.ts.net",
                     queue_store=temp_store())
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
