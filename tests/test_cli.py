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


def run_here(monkeypatch, tmp_path, argv, config_text='agent = "omp"\n'):
    """Run `ollagi here` up to the point where it would replace itself with tmux; return what it started."""
    import pytest

    from ollagi import cli, config, session_commands

    started = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("OLLAGI_CLAUDE", raising=False)
    monkeypatch.setattr(session_commands.config, "load", lambda: config.parse(config_text))
    monkeypatch.setattr(session_commands.sessions, "names", lambda: [])
    monkeypatch.setattr(session_commands.sessions, "start", lambda name, directory, command: started.update(command=command))
    monkeypatch.setattr(session_commands.time, "sleep", lambda seconds: None)

    def fake_exec(program, arguments):
        raise SystemExit(f"exec {program}")

    monkeypatch.setattr(session_commands.os, "execvp", fake_exec)
    with pytest.raises(SystemExit, match="exec tmux"):
        cli.main(argv)
    return started["command"]


def test_here_without_agent_starts_the_folders_agent_from_the_config(monkeypatch, tmp_path):
    assert run_here(monkeypatch, tmp_path, ["here"]) == ["omp"]


def test_here_with_agent_starts_that_agent_whatever_the_config_says(monkeypatch, tmp_path):
    # Typing `claude` must start Claude even where the config's agent is omp, and the other way round.
    assert run_here(monkeypatch, tmp_path, ["here", "--agent", "claude", "--", "--continue"]) == ["claude", "--continue"]
    assert run_here(monkeypatch, tmp_path, ["here", "--agent", "omp"], 'agent = "claude"\n') == ["omp"]


def test_here_refuses_an_unknown_agent(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["here", "--agent", "codex"])
    assert "invalid choice" in capsys.readouterr().err
