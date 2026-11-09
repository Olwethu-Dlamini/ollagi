import json
import os

from ollagi import omp_conversations, omp_state


def conversation(root, folder, conversation_id, cwd, title=None, mtime=0.0):
    """A file shaped like omp 18.12's: an optional title line, then the session line, then messages."""
    path = root / folder / f"2026-10-26T07-46-20-635Z_{conversation_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ([{"type": "title", "v": 1, "title": title}] if title else []) + [
        {"type": "session", "version": 3, "id": conversation_id, "cwd": cwd},
        {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def test_only_the_folders_conversations_are_listed_newest_first_with_their_titles(tmp_path):
    conversation(tmp_path, "-work-DATA-", "01a1-old", "/work/DATA!", "Old work", mtime=1000)
    conversation(tmp_path, "-work-DATA-", "01a1-new", "/work/DATA!", "SD-7119 close-out", mtime=3000)
    conversation(tmp_path, "-tmp", "01a1-tmp", "/tmp", "elsewhere", mtime=5000)
    found = omp_conversations.recent("/work/DATA!", root=tmp_path)
    assert [(c.session_id, c.title) for c in found] == [("01a1-new", "SD-7119 close-out"), ("01a1-old", "Old work")]


def test_a_conversation_without_a_title_yet_is_still_offered(tmp_path):
    # omp names a conversation after a few turns, and never in print mode.
    conversation(tmp_path, "-w", "01a1-x", "/w")
    assert [c.title for c in omp_conversations.recent("/w", root=tmp_path)] == ["(untitled)"]


def test_conversations_a_running_session_holds_are_left_out(tmp_path):
    conversation(tmp_path, "-w", "01a1-busy", "/w", mtime=2000)
    conversation(tmp_path, "-w", "01a1-free", "/w", mtime=1000)
    found = omp_conversations.recent("/w", root=tmp_path, leave_out=frozenset({"01a1-busy"}))
    assert [c.session_id for c in found] == ["01a1-free"]


def test_the_ids_running_sessions_hold_come_from_their_state_files(tmp_path):
    (tmp_path / "o-1.json").write_text(json.dumps({"state": "working", "conversation": "01a1-busy"}))
    (tmp_path / "o-2.json").write_text(json.dumps({"state": "idle", "conversation": None}))  # not saved yet
    (tmp_path / "o-3.json").write_text('{"state": "wor')  # cut off mid-write
    assert omp_state.open_conversations(tmp_path) == frozenset({"01a1-busy"})


def omp_process(proc, pid, ppid, tty_nr=34816, open_files=(), name="omp", start_ticks=500):
    """A process in a fake /proc, as much of it as running() reads: its name, parent, controlling
    terminal (0: none) and start time in `stat`, and the files it holds open."""
    folder = proc / str(pid)
    (folder / "fd").mkdir(parents=True)
    fields = ["S", str(ppid), "0", "0", str(tty_nr)] + ["0"] * 14 + [str(start_ticks)]  # fields 3-22
    (folder / "stat").write_text(f"{pid} ({name}) {' '.join(fields)}\n")
    (folder / "fd" / "0").symlink_to("/dev/null")  # omp points its input here while it runs a command
    for n, path in enumerate(open_files, start=3):
        (folder / "fd" / str(n)).symlink_to(path)


def fake_proc(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  1 2 3\nbtime 1000\n")
    return proc


def test_an_omp_started_in_a_terminal_is_listed_with_its_open_conversation(tmp_path):
    root, proc = tmp_path / "sessions", fake_proc(tmp_path)
    path = conversation(root, "-work-DATA-", "01a1-live", "/work/DATA!", "SD-7119 close-out", mtime=3000)
    # A subagent's file sits one folder deeper and has a session line of its own (omp 18.16).
    subagent = path.with_suffix("") / "Scout.jsonl"
    subagent.parent.mkdir()
    subagent.write_text(json.dumps({"type": "session", "id": "01a1-scout", "cwd": "/work/DATA!", "parentSession": str(path)}) + "\n")
    omp_process(proc, 2103, ppid=1, open_files=(subagent, path))
    omp_process(proc, 2200, ppid=1, open_files=(subagent,))  # a subagent's file alone is not a conversation
    [s] = omp_conversations.running(proc=proc, root=root)
    assert (s.pid, s.program, s.session_id, s.name, s.cwd, s.status) == (
        2103, "omp", "01a1-live", "SD-7119 close-out", "/work/DATA!", "unknown")
    assert s.transcript == str(path)
    assert s.updated == 3000
    assert s.started == 1000 + 500 / os.sysconf("SC_CLK_TCK")  # boot time plus the process's start


def test_omps_helpers_and_background_runs_are_not_sessions(tmp_path):
    root, proc = tmp_path / "sessions", fake_proc(tmp_path)
    path = conversation(root, "-w", "01a1-x", "/w", "Live one")
    omp_process(proc, 10, ppid=1, open_files=(path,))                    # the session in a terminal
    omp_process(proc, 11, ppid=10, open_files=(path,))                   # its helper: parent is omp
    omp_process(proc, 12, ppid=1, tty_nr=0, open_files=(path,))          # no terminal: a background run
    omp_process(proc, 13, ppid=1, open_files=(path,), name="bash")       # not omp at all
    omp_process(proc, 14, ppid=1)                                        # no conversation open yet
    assert [s.pid for s in omp_conversations.running(proc=proc, root=root)] == [10]


def test_sessions_are_found_when_the_sessions_folder_is_reached_through_a_symlink(tmp_path):
    # /proc names an open file by its real path; a home folder behind a symlink must not hide every session.
    real, proc = tmp_path / "real-sessions", fake_proc(tmp_path)
    path = conversation(real, "-w", "01a1-x", "/w", "Live one")
    (tmp_path / "linked").symlink_to(real)
    omp_process(proc, 10, ppid=1, open_files=(path,))
    assert [s.pid for s in omp_conversations.running(proc=proc, root=tmp_path / "linked")] == [10]


def test_an_omp_conversation_reads_as_prompts_replies_and_tool_lines(tmp_path):
    message = lambda role, *blocks: json.dumps({"type": "message", "message": {"role": role, "content": list(blocks)}})  # noqa: E731
    lines = [
        json.dumps({"type": "session", "id": "01a1-x", "cwd": "/w"}),
        message("user", {"type": "text", "text": "Why does login time out?"}),
        message("assistant", {"type": "thinking", "thinking": "hidden"},
                {"type": "toolCall", "name": "bash", "arguments": {"command": "grep -rn timeout src/", "i": "Finding the timeout"}}),
        message("toolResult", {"type": "text", "text": "src/a.py:3"}),
        message("developer", {"type": "text", "text": "<system-reminder>not typed by anyone</system-reminder>"}),
        message("assistant", {"type": "toolCall", "name": "read", "arguments": {"path": "src/a.py"}}),
        message("assistant", {"type": "text", "text": "The timeout is 10 s in a.py."}),
        json.dumps({"type": "title_change", "title": "Fix the login timeout"}),
        "not json at all",
    ]
    title, items = omp_conversations.parse_conversation(lines)
    assert title == "Fix the login timeout"
    assert [(i.role, i.text) for i in items] == [
        ("you", "Why does login time out?"),
        ("tool", "bash: Finding the timeout"),
        ("tool", "read: src/a.py"),
        ("claude", "The timeout is 10 s in a.py."),
    ]
