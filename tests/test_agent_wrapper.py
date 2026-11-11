"""deploy/agent-wrapper.bash: which typed `claude` and `omp` commands go through `ollagi here`.

Each case runs the wrapper in a real bash on a pseudo-terminal (the wrapper only takes over a person at a
terminal), with fake `ollagi`, `claude` and `omp` programs first on PATH that write down how they were
called.
"""

import os
import pty
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "deploy" / "agent-wrapper.bash"


@pytest.fixture
def bin_dir(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    for program in ("ollagi", "claude", "omp"):
        # One field per argument, so a lost quote ("fix the tests" split in three) changes the line.
        script = folder / program
        script.write_text(f'#!/bin/sh\n{{ printf %s {program}; for a; do printf "|%s" "$a"; done; echo; }} >> "$CALLS"\n')
        script.chmod(0o755)
    return folder


def typed(bin_dir, tmp_path, line, **env):
    """Run `line` in a bash that loaded the wrapper, at a terminal; return the programs it called."""
    calls = tmp_path / "calls"
    calls.write_text("")
    environment = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "CALLS": str(calls),
        "HOME": str(tmp_path),
        "TERM": "dumb",
        **env,
    }
    controller, terminal = pty.openpty()
    try:
        subprocess.run(
            ["bash", "--norc", "-c", f'source "{WRAPPER}"; {line}'],
            stdin=terminal, stdout=terminal, stderr=terminal, env=environment, timeout=10, check=True,
        )
    finally:
        os.close(controller)
        os.close(terminal)
    return calls.read_text().splitlines()


def test_a_chat_typed_at_a_terminal_starts_through_ollagi_with_that_agent(bin_dir, tmp_path):
    assert typed(bin_dir, tmp_path, "omp") == ["ollagi|here|--agent|omp|--"]
    assert typed(bin_dir, tmp_path, "omp 'fix the tests' --model opus") == [
        "ollagi|here|--agent|omp|--|fix the tests|--model|opus"
    ]
    assert typed(bin_dir, tmp_path, "claude --continue") == ["ollagi|here|--agent|claude|--|--continue"]


@pytest.mark.parametrize(
    "line",
    [
        "omp -p 'list files'",   # print mode
        "omp --mode rpc",        # a program talking to omp, not a person
        "omp --version",
        "omp --help",
        "omp git",               # a subcommand, not a chat
        "omp config get x",
        "claude mcp list",
        "claude --print hi",
    ],
)
def test_anything_that_is_not_an_interactive_chat_goes_straight_to_the_agent(bin_dir, tmp_path, line):
    program = line.split()[0]
    calls = typed(bin_dir, tmp_path, line)
    assert len(calls) == 1 and calls[0].startswith(f"{program}|")
    assert not calls[0].startswith("ollagi")


def test_inside_tmux_or_when_switched_off_the_agent_runs_directly(bin_dir, tmp_path):
    assert typed(bin_dir, tmp_path, "omp", TMUX="/tmp/tmux-1000/x,1,0") == ["omp"]
    assert typed(bin_dir, tmp_path, "omp", OLLAGI_OFF="1") == ["omp"]


def test_without_a_terminal_the_agent_runs_directly(bin_dir, tmp_path):
    calls = tmp_path / "calls"
    calls.write_text("")
    subprocess.run(
        ["bash", "--norc", "-c", f'source "{WRAPPER}"; omp'],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "CALLS": str(calls), "HOME": str(tmp_path)},
    )
    assert calls.read_text().splitlines() == ["omp"]
