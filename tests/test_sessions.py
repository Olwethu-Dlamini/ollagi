import os
import shutil
import subprocess
import time

import pytest

from ollagi import sessions


class FakeRun:
    """Records every command instead of running it, and answers with a chosen result."""

    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def test_names_must_be_short_lowercase_and_safe():
    assert sessions.check_name("sd-6641") == "sd-6641"
    for bad in ["", "SD", "a b", "-x", "a" * 33, "../etc", "x;rm"]:
        with pytest.raises(ValueError):
            sessions.check_name(bad)


def test_start_runs_tmux_inside_its_own_systemd_scope():
    argv = sessions.start_command("sd-6641", "/work/repo", ["claude"])
    assert argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
    assert "--unit=ollagi-sd-6641" in argv
    assert "ManagedOOMMemoryPressure=kill" in argv
    tmux_part = argv[argv.index("tmux"):]
    assert tmux_part[:3] == ["tmux", "-L", "ollagi-sd-6641"]
    assert tmux_part[-2:] == ["--", "claude"]
    assert ["-c", "/work/repo"] == tmux_part[tmux_part.index("-c"):tmux_part.index("-c") + 2]


def test_text_is_sent_literally_then_enter_is_pressed():
    fake = FakeRun()
    sessions.send_text("demo", "Enter the room; rm -rf /", run=fake)
    assert fake.calls[0][-2:] == ["-l", "Enter the room; rm -rf /"]
    assert fake.calls[1][-1] == "Enter"


def test_only_allowed_keys_can_be_pressed():
    fake = FakeRun()
    sessions.send_key("demo", "Escape", run=fake)
    assert fake.calls[0][-1] == "Escape"
    with pytest.raises(ValueError):
        sessions.send_key("demo", "C-b", run=fake)  # the tmux prefix key could reach tmux itself


def test_display_output_is_parsed_into_folder_pid_time_and_state():
    assert sessions.parse_display("demo", "4242|1792400000|0|/work/my repo\n") == ("/work/my repo", 4242, 1792400000, True)
    assert sessions.parse_display("demo", "4242|1792400000|1|/w\n")[3] is False


def test_names_skips_sockets_whose_server_is_gone(tmp_path):
    (tmp_path / "ollagi-alive").touch()
    (tmp_path / "ollagi-stale").touch()
    (tmp_path / "default").touch()  # someone's own tmux, not ours

    def fake(argv):
        alive = argv[2] == "ollagi-alive"
        return subprocess.CompletedProcess(argv, 0 if alive else 1, "", "")

    assert sessions.names(socket_dir=tmp_path, run=fake) == ["alive"]


def test_cgroup_events_say_whether_the_scope_is_frozen():
    assert sessions.parse_events("populated 1\nfrozen 1\n") is True
    assert sessions.parse_events("populated 1\nfrozen 0\n") is False


def test_a_saved_record_round_trips(tmp_path):
    sessions.save_record("demo", {"directory": "/w", "created": 5}, state_dir=tmp_path)
    assert sessions.load_record("demo", state_dir=tmp_path) == {"directory": "/w", "created": 5}
    assert sessions.load_record("other", state_dir=tmp_path) == {}


needs_tmux = pytest.mark.skipif(
    not (shutil.which("tmux") and shutil.which("systemd-run")), reason="needs tmux and a systemd user session"
)


@needs_tmux
def test_a_real_session_starts_shows_output_takes_input_and_stops(tmp_path):
    """Uses a harmless shell instead of claude, so the test costs no tokens."""
    name = f"test-{os.getpid()}"
    script = "echo ready; read line; echo got:$line; exec sleep 60"
    sessions.start(name, str(tmp_path), ["sh", "-c", script])
    try:
        assert name in sessions.names()
        _wait_for(lambda: "ready" in sessions.screen(name))
        sessions.send_text(name, "hello")
        _wait_for(lambda: "got:hello" in sessions.screen(name))
        details = sessions.info(name)
        assert details.directory == str(tmp_path)
        assert details.alive
        assert details.memory_current is not None and details.memory_current > 0
        # Frozen: listing and info must answer without asking the (paused) tmux server.
        sessions.freeze(name)
        _wait_for(lambda: sessions.scope_state(name)[0])
        assert name in sessions.names()
        assert sessions.info(name).frozen
        assert sessions.info(name).directory == str(tmp_path)
    finally:
        sessions.stop(name)  # must work while frozen: stop thaws first
    _wait_for(lambda: name not in sessions.names())
    assert not (sessions.Path(f"/tmp/tmux-{os.getuid()}") / f"ollagi-{name}").exists()


def _wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError("condition not met in time")
