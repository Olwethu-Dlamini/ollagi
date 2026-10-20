from ollagi import desktop
from ollagi.config import parse

ON_DESKTOP = {"WAYLAND_DISPLAY": "wayland-1"}


class FakePopen:
    """Records what would be started instead of opening a real window."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **options):
        self.calls.append((list(argv), options))


def test_the_window_runs_the_terminal_with_tmux_attached_to_the_session():
    command = desktop.window_command("calendar", desktop.Settings(), ON_DESKTOP, launcher=["uwsm", "app", "--"])
    assert command == [
        "uwsm", "app", "--",
        "foot", "-T", "ollagi: calendar",
        "tmux", "-L", "ollagi-calendar", "attach-session", "-t", "main",
    ]


def test_another_terminal_can_be_named_and_gets_the_session_name():
    settings = desktop.Settings(terminal=("kitty", "--title", "ollagi {name}"))
    command = desktop.window_command("data-3f2a", settings, ON_DESKTOP, launcher=[])
    assert command[:3] == ["kitty", "--title", "ollagi data-3f2a"]
    assert command[3:] == ["tmux", "-L", "ollagi-data-3f2a", "attach-session", "-t", "main"]


def test_no_window_without_a_desktop_to_show_it_on():
    assert desktop.window_command("calendar", desktop.Settings(), {}, launcher=[]) is None
    popen = FakePopen()
    assert desktop.open_window("calendar", desktop.Settings(), {}, popen=popen) is False
    assert popen.calls == []


def test_the_window_is_started_without_waiting_for_it_and_outside_ollagi():
    popen = FakePopen()
    assert desktop.open_window("calendar", desktop.Settings(), ON_DESKTOP, popen=popen) is True
    argv, options = popen.calls[0]
    assert "ollagi-calendar" in argv
    # Its own session, no shared input or output: closing ollagi must not close the window.
    assert options["start_new_session"] is True
    assert options["stdin"] == options["stdout"] == options["stderr"] == desktop.subprocess.DEVNULL


def test_desktop_settings_default_to_foot_and_opening_on_start():
    settings = parse("").desktop
    assert settings.open_on_start is True
    assert settings.terminal == ("foot", "-T", "ollagi: {name}")


def test_desktop_settings_can_be_changed():
    settings = parse('[desktop]\nopen_on_start = false\nterminal = ["kitty", "--title", "{name}"]\n').desktop
    assert settings.open_on_start is False
    assert settings.terminal == ("kitty", "--title", "{name}")


def fake_cli(monkeypatch, running=("demo",), desktop_running=True, open_on_start=True):
    """Replaces what the terminal commands call, and records the windows they ask for."""
    from ollagi import config, session_commands

    opened = []

    def open_window(name, settings):
        if desktop_running:
            opened.append(name)
        return desktop_running

    monkeypatch.setattr(session_commands.desktop, "open_window", open_window)
    monkeypatch.setattr(session_commands.sessions, "names", lambda: list(running))
    monkeypatch.setattr(session_commands.sessions, "start", lambda name, directory, command: None)
    monkeypatch.setattr(config, "load", lambda: config.Config(desktop=desktop.Settings(open_on_start=open_on_start)))
    return opened


def test_ollagi_start_opens_a_window_unless_told_not_to(monkeypatch, tmp_path):
    from ollagi.cli import main

    opened = fake_cli(monkeypatch)
    assert main(["start", "sd-1", str(tmp_path), "--force"]) == 0
    assert main(["start", "sd-2", str(tmp_path), "--force", "--no-window"]) == 0
    assert opened == ["sd-1"]


def test_ollagi_start_opens_no_window_when_switched_off(monkeypatch, tmp_path):
    from ollagi.cli import main

    opened = fake_cli(monkeypatch, open_on_start=False)
    assert main(["start", "sd-1", str(tmp_path), "--force"]) == 0
    assert opened == []


def test_ollagi_open_shows_a_running_session_and_says_why_it_cannot(monkeypatch, capsys):
    from ollagi.cli import main

    opened = fake_cli(monkeypatch)
    assert main(["open", "demo"]) == 0
    assert opened == ["demo"]
    assert main(["open", "nope"]) == 1
    assert "no ollagi session called nope" in capsys.readouterr().out

    fake_cli(monkeypatch, desktop_running=False)
    assert main(["open", "demo"]) == 1
    assert "no desktop" in capsys.readouterr().out


class FakeRun:
    """Answers tmux like a session with the given terminals attached, and records the commands."""

    def __init__(self, terminals=("/dev/pts/3",), returncode=0):
        self.calls = []
        self.terminals = terminals
        self.returncode = returncode

    def __call__(self, argv):
        import subprocess

        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, "".join(t + "\n" for t in self.terminals), "")


def test_windows_are_counted_from_the_terminals_attached_to_the_session():
    run = FakeRun(terminals=("/dev/pts/3", "/dev/pts/7"))
    assert desktop.count_windows("calendar", run=run) == 2
    assert run.calls == [["tmux", "-L", "ollagi-calendar", "list-clients", "-F", "#{client_tty}"]]
    assert desktop.count_windows("calendar", run=FakeRun(terminals=())) == 0
    # A session whose tmux is gone has no windows, not an error.
    assert desktop.count_windows("calendar", run=FakeRun(returncode=1)) == 0


def test_closing_detaches_every_terminal_and_leaves_the_session_running():
    run = FakeRun(terminals=("/dev/pts/3", "/dev/pts/7"))
    assert desktop.close_windows("calendar", run=run) == 2
    assert run.calls[-1] == ["tmux", "-L", "ollagi-calendar", "detach-client", "-s", "main"]
    assert not any("kill" in word for call in run.calls for word in call)


def test_closing_with_no_window_open_does_nothing():
    run = FakeRun(terminals=())
    assert desktop.close_windows("calendar", run=run) == 0
    assert all("detach-client" not in call for call in run.calls)


def test_ollagi_close_closes_the_windows_of_a_running_session(monkeypatch, capsys):
    from ollagi.cli import main

    fake_cli(monkeypatch)
    closed = []
    monkeypatch.setattr(desktop, "close_windows", lambda name: closed.append(name) or 1)
    assert main(["close", "demo"]) == 0
    assert closed == ["demo"]
    assert main(["close", "nope"]) == 1
