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


def test_start_runs_tmux_in_a_scope_inside_the_sessions_own_slice():
    argv = sessions.start_command("sd-6641", "/work/repo", ["claude"])
    assert argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
    assert "--unit=ollagi-sd\\x2d6641" in argv
    assert "--slice=app-ollagi-sd\\x2d6641.slice" in argv
    tmux_part = argv[argv.index("tmux"):]
    assert tmux_part[:2] == ["tmux", "-f"] and tmux_part[2].endswith("tmux.conf")
    assert tmux_part[3:5] == ["-L", "ollagi-sd-6641"]
    assert tmux_part[-2:] == ["--", "claude"]
    assert ["-c", "/work/repo"] == tmux_part[tmux_part.index("-c"):tmux_part.index("-c") + 2]
    # The session's name travels in its environment, so omp's state hook can name its file (0036).
    assert tmux_part[tmux_part.index("-e"):tmux_part.index("-e") + 2] == ["-e", "OLLAGI_SESSION=sd-6641"]
    assert tmux_part.index("-e") < tmux_part.index("--")


def test_dashes_are_escaped_so_one_sessions_slice_never_nests_inside_another():
    # Unescaped, "sd-6641" would become app-ollagi-sd-6641.slice, which systemd places inside
    # app-ollagi-sd.slice: freezing a session called "sd" would freeze this one too.
    assert sessions.slice_unit("sd-6641") == "app-ollagi-sd\\x2d6641.slice"
    assert sessions.slice_unit("sd") == "app-ollagi-sd.slice"


def test_session_names_come_from_the_folder():
    assert sessions.name_for("/work/Admin-Frontend", [], "3f2a") == "admin-frontend-3f2a"
    assert sessions.name_for("/run/media/oll/Linux/SIMEDIA/DATA!", [], "01") == "data-01"
    assert sessions.name_for("/", [], "01") == "session-01"
    assert sessions.check_name(sessions.name_for("/x/Über Projekt (2)", [], "a1"))


def test_ollagi_tmux_settings_free_ctrl_b_for_claude_and_make_esc_instant():
    conf = sessions.TMUX_CONF.read_text()
    assert "set -g prefix C-]" in conf and "unbind C-b" in conf
    assert "set -g escape-time 10" in conf


def test_text_is_sent_literally_then_enter_is_pressed():
    fake = FakeRun()
    sessions.send_text("demo", "Enter the room; rm -rf /", run=fake)
    assert fake.calls[1][-2:] == ["-l", "Enter the room; rm -rf /"]
    assert fake.calls[2][-1] == "Enter"


def test_sending_first_leaves_scrollback(tmp_path):
    # Scrolled up, tmux reads keys as scroll commands; typed text would be lost. So every send first
    # returns to the live screen, if (and only if) the pane is scrolled.
    fake = FakeRun()
    sessions.send_text("demo", "hi", run=fake)
    sessions.send_key("demo", "Enter", run=fake)
    leave = ["if-shell", "-F", "-t", "main", "#{pane_in_mode}", "send-keys -t main -X cancel"]
    assert fake.calls[0][-6:] == leave and fake.calls[3][-6:] == leave


def test_only_allowed_keys_can_be_pressed():
    fake = FakeRun()
    sessions.send_key("demo", "Escape", run=fake)
    assert fake.calls[-1][-1] == "Escape"
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


def test_a_session_remembers_what_it_runs():
    # The page tags a session that is not Claude, and the notifier leaves it alone (decision 0027).
    assert sessions.program_of(["claude"]) == "claude"
    assert sessions.program_of(["claude", "--resume", "conv-1"]) == "claude"
    assert sessions.program_of(["/usr/bin/bash"]) == "bash"
    assert sessions.program_of([]) == "claude"


def test_the_login_shell_comes_from_the_password_database():
    import pwd

    assert sessions.login_shell() == (pwd.getpwuid(os.getuid()).pw_shell or "bash")


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
    # Python holds 30 MiB (written, so the memory is really used), then the shell talks.
    hold = "python3 -c 'import time; x = bytes([1]) * (30 << 20); time.sleep(120)' &"
    script = f"{hold} echo ready; read line; echo got:$line; exec sleep 60"
    sessions.start(name, str(tmp_path), ["sh", "-c", script])
    try:
        assert name in sessions.names()
        _wait_for(lambda: "ready" in sessions.screen(name))
        # Scrolled up the way a mouse wheel or a swipe does it; the text must still reach the program.
        subprocess.run(sessions.tmux(name, "copy-mode", "-t", "main"), check=True)
        sessions.send_text(name, "hello")
        _wait_for(lambda: "got:hello" in sessions.screen(name))
        details = sessions.info(name)
        assert details.directory == str(tmp_path)
        assert details.alive
        # The program tmux started must be counted, not just the tmux server: tmux moves it into a
        # scope of its own, and only the session's slice holds both.
        _wait_for(lambda: (sessions.info(name).memory_current or 0) >= 30 << 20)
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


@needs_tmux
def test_a_view_frozen_at_the_live_screen_comes_back_live(tmp_path):
    """Found on 2026-10-26: a session sat in tmux's scroll mode at the bottom, so every screen looking
    at it (phone and laptop) stopped following the program, which read as "ollagi is slow"."""
    from ollagi import terminal

    name = f"test-frz-{os.getpid()}"
    sessions.start(name, str(tmp_path), ["sh", "-c", "seq 1 300; echo ready; exec sleep 60"])
    in_mode = lambda: _pane(name, "#{pane_in_mode}") == "1"
    try:
        _wait_for(lambda: "ready" in sessions.screen(name))
        # Entered the way a mouse selection enters it (no -e), while showing the live screen.
        subprocess.run(sessions.tmux(name, "copy-mode", "-t", "main"), check=True)
        # A wheel turned down in a real attached terminal must leave it, though nothing is left to scroll.
        term = terminal.Terminal(terminal.session_command(name), 24, 80)
        try:
            _wait_for(lambda: bool(term.read()))
            term.write(b"\x1b[<65;5;5M")
            _wait_for(lambda: not in_mode())
        finally:
            term.close()
        # Scrolled up to read: opening the session on the page must leave the reader where they are.
        subprocess.run(sessions.tmux(name, "copy-mode", "-t", "main", "-u"), check=True)
        sessions.leave_frozen_bottom(name)
        assert in_mode()
        # Back at the bottom but still in scroll mode: opening the session releases it.
        subprocess.run(sessions.tmux(name, "send-keys", "-t", "main", "-X", "history-bottom"), check=True)
        sessions.leave_frozen_bottom(name)
        assert not in_mode()
    finally:
        sessions.stop(name)


def _pane(name, format_):
    return subprocess.run(sessions.tmux(name, "display", "-p", "-t", "main", format_),
                          capture_output=True, text=True).stdout.strip()


def _wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError("condition not met in time")
