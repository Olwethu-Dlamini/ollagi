from ollagi import __version__
from ollagi.cli import main


def test_no_command_prints_help_and_succeeds(capsys):
    assert main([]) == 0
    assert "usage: ollagi" in capsys.readouterr().out


def test_version_flag_reports_the_package_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exit_:
        # argparse exits after printing the version; exit code 0 means success.
        assert exit_.code == 0
    assert capsys.readouterr().out.strip() == f"ollagi {__version__}"


def test_start_with_shell_runs_my_login_shell_and_skips_the_budget(tmp_path, monkeypatch, capsys):
    from ollagi import cli, session_commands

    started = {}
    monkeypatch.setattr(session_commands.sessions, "start", lambda name, directory, command: started.update({name: command}))
    monkeypatch.setattr(session_commands.sessions, "login_shell", lambda: "/usr/bin/bash")
    monkeypatch.setattr(session_commands.desktop, "open_window", lambda name, settings: False)
    # No memory at all: a Claude session would be refused, a shell is not.
    monkeypatch.setattr(session_commands, "read_memory", lambda: (_ for _ in ()).throw(AssertionError("budget asked")))
    assert cli.main(["start", "sh-1", str(tmp_path), "--shell"]) == 0
    assert started == {"sh-1": ["/usr/bin/bash"]}
    assert "started sh-1" in capsys.readouterr().out
