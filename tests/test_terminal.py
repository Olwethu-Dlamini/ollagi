"""The live terminal (docs/decisions/0018) runs real programs in a real pseudo-terminal here, but
small ones (sh, cat) instead of tmux, so no session is needed."""

import time

import pytest

from ollagi import terminal
from ollagi.terminal import Input, Resize, Terminal


def output_until(term: Terminal, wanted: str, seconds: float = 5.0) -> str:
    """Everything the program printed, read until `wanted` appears (or the time runs out)."""
    seen = b""
    deadline = time.monotonic() + seconds
    while wanted.encode() not in seen and time.monotonic() < deadline:
        try:
            seen += term.read()
        except EOFError:
            break
        time.sleep(0.02)
    return seen.decode(errors="replace")


@pytest.fixture
def opened():
    terminals = []

    def start(argv, rows=24, cols=80):
        term = Terminal(argv, rows, cols)
        terminals.append(term)
        return term

    yield start
    for term in terminals:
        term.close()


def test_the_page_sends_typing_and_size_changes_as_small_json_messages():
    assert terminal.parse('{"type": "input", "data": "ls\\r"}') == Input("ls\r")
    assert terminal.parse('{"type": "resize", "rows": 40, "cols": 120}') == Resize(40, 120)


@pytest.mark.parametrize("message", [
    "not json",
    '{"type": "input"}',
    '{"type": "input", "data": 5}',
    '{"type": "resize", "rows": 0, "cols": 80}',
    '{"type": "resize", "rows": 40, "cols": 100000}',
    '{"type": "resize", "rows": "40", "cols": 80}',
    '{"type": "run", "command": "rm -rf ~"}',
    '[1, 2]',
])
def test_anything_else_is_refused(message):
    with pytest.raises(ValueError):
        terminal.parse(message)


def test_the_program_starts_at_the_size_the_page_asked_for(opened):
    term = opened(["sh", "-c", "stty size; sleep 5"], rows=30, cols=100)
    assert "30 100" in output_until(term, "30 100")


def test_typing_reaches_the_program_and_its_answer_comes_back(opened):
    term = opened(["cat"])
    term.write(b"hello\n")
    assert "hello" in output_until(term, "hello")


def test_a_resize_reaches_the_program(opened):
    term = opened(["sh", "-c", "read line; stty size; sleep 5"])
    term.resize(40, 120)
    assert terminal.size(term.fd) == (40, 120)
    term.write(b"\n")
    assert "40 120" in output_until(term, "40 120")


def test_the_program_owns_the_terminal_so_it_is_told_about_a_resize(opened):
    # The kernel signals a resize (SIGWINCH) only to the programs whose controlling terminal it is;
    # `setsid -c` makes it theirs. Without it tmux would keep drawing at the old size.
    term = opened(["sh", "-c", "trap 'echo resized' WINCH; echo ready; while :; do sleep 0.05; done"])
    assert "ready" in output_until(term, "ready")
    term.resize(33, 90)
    assert "resized" in output_until(term, "resized")


def test_the_program_is_marked_as_a_browser_terminal(opened):
    # desktop.py leaves clients with this mark out of the laptop's window count.
    term = opened(["sh", "-c", 'echo "[$OLLAGI_VIEWER $TERM ${TMUX:-none}]"; sleep 5'])
    assert "[browser xterm-256color none]" in output_until(term, "]")


def test_reading_after_the_program_ended_says_so(opened):
    term = opened(["sh", "-c", "echo bye"])
    output_until(term, "bye")
    with pytest.raises(EOFError):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            term.read()
            time.sleep(0.02)


def test_closing_ends_the_program(opened):
    term = opened(["sleep", "30"])
    term.close()
    assert term.process.poll() is not None


def test_the_session_command_attaches_tmux_to_the_session():
    assert terminal.session_command("calendar") == ["tmux", "-L", "ollagi-calendar", "attach-session", "-t", "main"]


def test_the_laptop_window_count_recognises_a_browser_terminal_from_its_real_environment(opened):
    from ollagi import desktop

    term = opened(["sleep", "5"])
    assert desktop.in_browser(term.process.pid)
