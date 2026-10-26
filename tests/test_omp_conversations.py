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
