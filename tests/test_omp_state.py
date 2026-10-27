import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ollagi import omp_state
from ollagi.claude_screen import Option

HOOK = Path(__file__).parent.parent / "deploy" / "omp" / "ollagi-state.ts"


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


# Drives the real hook file with a stand-in for omp's hook API: its `on` handlers and the shared event
# bus every hook and extension in one omp process gets (`pi.events`). Node runs the TypeScript as is.
DRIVE = """
const handlers = {}, bus = {};
const pi = {
  on: (name, fn) => { handlers[name] = fn; },
  events: { on: (name, fn) => { (bus[name] ||= []).push(fn); }, emit: (name, data) => (bus[name] || []).forEach(f => f(data)) },
};
const hook = (await import(process.argv[1])).default;
hook(pi);
const fs = await import("node:fs");
const now = () => JSON.parse(fs.readFileSync(`${process.env.XDG_RUNTIME_DIR}/ollagi/${process.env.OLLAGI_SESSION}.json`, "utf8"));
handlers.session_start({}, {});
handlers.agent_start({}, {});
pi.events.emit("ui:waiting", { question: "Guard: confirm command", options: ["Yes", "No"] });
const waiting = now();
pi.events.emit("ui:answered", {});
console.log(JSON.stringify([waiting, now()]));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the hook")
def test_a_dialog_from_another_extension_reads_as_needs_you_until_answered(tmp_path):
    # Found 2026-10-26: the guard's Yes/No confirmation waited 35 minutes (then hours) while the page and
    # the phone said "working"; the hook only saw omp's ask tool. A dialog now announces itself on the bus.
    env = {**os.environ, "OLLAGI_SESSION": "g6-close-out", "XDG_RUNTIME_DIR": str(tmp_path)}
    run = subprocess.run(["node", "--input-type=module", "-e", DRIVE, str(HOOK)], env=env,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    waiting, answered = json.loads(run.stdout)
    assert (waiting["state"], waiting["question"], waiting["options"]) == ("needs_you", "Guard: confirm command", ["Yes", "No"])
    assert answered["state"] == "working"
    assert omp_state.read("g6-close-out", tmp_path / "ollagi").state == "working"
