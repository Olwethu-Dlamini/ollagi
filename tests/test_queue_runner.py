"""The queue runner, driven step by step with a fake sessions module that shows real Claude screens."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ollagi.queue import Runner, Store

FIXTURES = Path(__file__).parent / "fixtures" / "collie"
WORKING = (FIXTURES / "claude--working.txt").read_text()
DONE = (FIXTURES / "claude-lab--idle-after-turn--w82.txt").read_text()
ASKING = (FIXTURES / "claude--permission-bash.txt").read_text()
IDLE = (FIXTURES / "claude--v2301-idle.txt").read_text()


class FakeSessions:
    def __init__(self):
        self.running, self.screens, self.stopped, self.frozen = {}, {}, [], set()

    def start(self, name, directory, command):
        self.running[name] = command
        self.screens[name] = IDLE

    def names(self):
        return list(self.running)

    def info(self, name):
        # The real sessions.info reports the program from the session's record: "claude" or "omp".
        return SimpleNamespace(program=Path(self.running[name][0]).name)

    def scope_state(self, name):
        return name in self.frozen, 1, 1

    def screen(self, name, lines=80):
        return self.screens[name]

    def stop(self, name):
        self.stopped.append(name)
        self.running.pop(name, None)


@pytest.fixture
def setup(tmp_path):
    store, fake, room = Store(tmp_path / "q.db"), FakeSessions(), {"ok": True}
    runner = Runner(store, fake, room=lambda: room["ok"], results_dir=tmp_path / "results")
    return store, fake, runner, room, tmp_path


def test_a_task_runs_from_queued_to_done_and_its_result_is_kept(setup):
    store, fake, runner, _, tmp = setup
    task = store.add(str(tmp), "fix the failing test")
    assert runner.step(0) == "task 1 started as session q1"
    assert fake.running["q1"] == ["claude", "fix the failing test"]
    fake.screens["q1"] = WORKING
    runner.step(5)
    assert store.get(task.id).seen_working
    fake.screens["q1"] = DONE
    assert runner.step(10) == "task 1 done"
    assert store.get(task.id).status == "done"
    assert fake.stopped == ["q1"]
    assert "fix the failing test" in (tmp / "results" / "task-1.txt").read_text()


def test_only_one_task_runs_at_a_time(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "first")
    store.add(str(tmp), "second")
    runner.step(0)
    fake.screens["q1"] = WORKING
    runner.step(5)
    assert list(fake.running) == ["q1"]  # second waits


def test_a_quick_task_seen_only_when_done_still_counts_as_done(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "tiny")
    runner.step(0)
    fake.screens["q1"] = DONE  # finished between two checks: never seen working
    assert runner.step(5) == "task 1 done"


def test_a_question_holds_the_queue_until_answered(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "first")
    store.add(str(tmp), "second")
    runner.step(0)
    fake.screens["q1"] = ASKING
    assert runner.step(5) == "task 1 is waiting for you: Do you want to proceed?"
    runner.step(10)
    assert list(fake.running) == ["q1"]
    fake.screens["q1"] = WORKING  # answered on the phone; Claude carries on
    runner.step(15)
    assert store.get(1).status == "running"


def test_a_usage_limit_pauses_the_whole_queue(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "first")
    store.add(str(tmp), "second")
    runner.step(0)
    fake.screens["q1"] = "● Working on it\n5-hour limit reached ∙ resets 3pm\n"
    assert "queue paused" in runner.step(5)
    assert store.paused()
    assert runner.step(10) == ""  # task 2 does not start while paused
    assert store.get(2).status == "queued"


def test_nothing_starts_without_room(setup):
    store, fake, runner, room, tmp = setup
    store.add(str(tmp), "first")
    room["ok"] = False
    assert runner.step(0) == ""
    room["ok"] = True
    assert runner.step(5).startswith("task 1 started")


def test_a_task_whose_agent_never_works_fails_after_five_minutes(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "first")
    runner.step(0)  # screen stays idle
    assert runner.step(200) == ""
    assert runner.step(301) == "task 1 failed: the agent never started working"
    assert fake.stopped == ["q1"]


def test_a_frozen_task_is_left_alone(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "first")
    runner.step(0)
    fake.frozen.add("q1")
    fake.screens["q1"] = "this would hang a real frozen tmux"
    assert runner.step(1000) == ""
    assert store.get(1).status == "running"


def test_a_session_stopped_by_hand_fails_its_task(setup):
    store, fake, runner, _, tmp = setup
    store.add(str(tmp), "first")
    runner.step(0)
    fake.stop("q1")
    assert runner.step(5) == "task 1 failed: its session ended"


def test_a_task_in_an_omp_folder_runs_omp_and_follows_its_hook(tmp_path):
    # docs/decisions/0035 and 0036: the folder's agent runs the prompt; omp's state comes from its
    # hook, so its screen (here still Claude's idle screen) is not what decides.
    from ollagi.agents import get
    from ollagi.claude_screen import Reading

    store, fake = Store(tmp_path / "q.db"), FakeSessions()
    reported = {"q1": Reading("unknown")}
    runner = Runner(store, fake, room=lambda: True, agent_for=lambda directory: get("omp"),
                    omp_states=lambda name: reported[name], results_dir=tmp_path / "results")
    task = store.add(str(tmp_path), "close out SD-7104")
    runner.step(0)
    assert fake.running["q1"] == ["omp", "close out SD-7104"]
    reported["q1"] = Reading("working")
    runner.step(5)
    assert store.get(task.id).seen_working
    reported["q1"] = Reading("needs_you", question="Approve the plan?")
    assert runner.step(10) == "task 1 is waiting for you: Approve the plan?"
    reported["q1"] = Reading("done")
    assert runner.step(15) == "task 1 done"
    assert fake.stopped == ["q1"]
