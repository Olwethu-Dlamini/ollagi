"""Reading Claude's own session files. Every line here is invented: this repo is public."""

import json
import os

from ollagi.outside import list_sessions, parse_conversation, process_start, read_tail, transcript_path


def entry(**fields):
    return json.dumps(fields)


CONVERSATION = [
    entry(type="ai-title", aiTitle="Fix the login timeout"),
    entry(type="user", message={"role": "user", "content": "Why does login time out?"}),
    entry(type="assistant", message={"role": "assistant", "content": [{"type": "thinking", "thinking": "hidden"}]}),
    entry(type="assistant", message={"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "grep -rn timeout src/\nsecond line"}}]}),
    entry(type="user", message={"role": "user", "content": [{"type": "tool_result", "content": "src/a.py:3"}]}),
    entry(type="assistant", isSidechain=True, message={"role": "assistant", "content": [{"type": "text", "text": "subagent"}]}),
    entry(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": "The timeout is 10 s in a.py."}]}),
    "not json at all",
]


def test_a_conversation_keeps_prompts_answers_and_tool_lines_but_not_thinking_or_subagents():
    title, items = parse_conversation(CONVERSATION)
    assert title == "Fix the login timeout"
    assert [(i.role, i.text) for i in items] == [
        ("you", "Why does login time out?"),
        ("tool", "Bash: grep -rn timeout src/"),
        ("claude", "The timeout is 10 s in a.py."),
    ]


def test_only_the_last_items_are_kept():
    lines = [entry(type="user", message={"content": f"prompt {n}"}) for n in range(100)]
    assert [i.text for i in parse_conversation(lines, limit=3)[1]] == ["prompt 97", "prompt 98", "prompt 99"]


def test_the_tail_of_a_big_file_drops_its_cut_first_line(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(f"line {n:04d}" for n in range(1000)))
    lines = read_tail(f, max_bytes=100)
    assert lines[-1] == "line 0999"
    assert all(line.startswith("line ") and len(line) == 9 for line in lines)  # no half line


def test_running_sessions_are_listed_and_stale_files_skipped(tmp_path):
    me = os.getpid()
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / f"{me}.json").write_text(json.dumps({
        "pid": me, "sessionId": "abc-123", "cwd": "/work/demo", "name": "demo-1", "status": "idle",
        "kind": "interactive", "procStart": process_start(me), "startedAt": 1000, "updatedAt": 2000}))
    # The same pid number with another start time: a file left behind by an earlier process.
    (tmp_path / "sessions" / "1.json").write_text(json.dumps({"pid": 1, "kind": "interactive", "procStart": "nope"}))
    (tmp_path / "sessions" / "broken.json").write_text("{")
    [s] = list_sessions(claude_home=tmp_path)
    assert (s.pid, s.session_id, s.name, s.status, s.started) == (me, "abc-123", "demo-1", "idle", 1.0)


def test_a_one_shot_claude_p_run_is_not_a_session_started_in_a_terminal(tmp_path):
    # `claude -p` (ollagi's summaries, decision 0019) also writes a session file marked
    # "interactive", but its entrypoint says "sdk-cli"; a terminal session says "cli".
    me = os.getpid()
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / f"{me}.json").write_text(json.dumps({
        "pid": me, "sessionId": "p-1", "kind": "interactive", "entrypoint": "sdk-cli",
        "procStart": process_start(me)}))
    assert list_sessions(claude_home=tmp_path) == []


def test_a_conversation_file_is_found_by_its_id_in_any_project_folder(tmp_path):
    folder = tmp_path / "projects" / "-work-demo"
    folder.mkdir(parents=True)
    (folder / "abc-123.jsonl").write_text("")
    assert transcript_path("abc-123", claude_home=tmp_path) == folder / "abc-123.jsonl"
    assert transcript_path("../etc", claude_home=tmp_path) is None
