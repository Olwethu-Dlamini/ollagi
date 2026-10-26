import json

from ollagi import omp_state
from ollagi.claude_screen import Option


def write(folder, name, record):
    (folder / f"{name}.json").write_text(json.dumps(record))


def test_a_question_reads_as_needs_you_with_numbered_choices(tmp_path):
    # What deploy/omp/ollagi-state.ts writes when omp's ask tool runs.
    write(tmp_path, "sd-7119", {"state": "needs_you", "question": "Approve the plan?", "options": ["Yes", "No"],
                                "updated": 1.0, "pid": 4242})
    reading = omp_state.read("sd-7119", tmp_path)
    assert reading.state == "needs_you"
    assert reading.question == "Approve the plan?"
    assert reading.options == [Option(1, "Yes"), Option(2, "No")]


def test_no_file_yet_reads_as_unknown_not_as_a_guess(tmp_path):
    # omp still starting, or the hook is not installed: the page must not claim "idle".
    assert omp_state.read("sd-1", tmp_path).state == "unknown"


def test_a_damaged_file_or_a_state_we_do_not_know_reads_as_unknown(tmp_path):
    (tmp_path / "a.json").write_text('{"state": "work')  # cut off mid-write by a crash
    assert omp_state.read("a", tmp_path).state == "unknown"
    write(tmp_path, "b", {"state": "thinking"})
    assert omp_state.read("b", tmp_path).state == "unknown"


def test_the_hook_and_ollagi_agree_on_the_folder(monkeypatch, tmp_path):
    # The hook writes to $XDG_RUNTIME_DIR/ollagi; without that variable both fall back to /tmp.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert omp_state.runtime_dir() == tmp_path / "ollagi"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert str(omp_state.runtime_dir()).startswith("/tmp/ollagi-")
