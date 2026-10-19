import pytest

from ollagi.queue import Store, hit_limit


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "queue.db")


def test_tasks_are_added_queued_and_come_out_in_order(store, tmp_path):
    first = store.add(str(tmp_path), "fix the failing test")
    store.add(str(tmp_path), "write the docs")
    assert first.status == "queued"
    assert store.next_queued().prompt == "fix the failing test"
    assert [t.prompt for t in store.all()] == ["fix the failing test", "write the docs"]


def test_a_task_needs_a_prompt_and_a_real_folder(store, tmp_path):
    with pytest.raises(ValueError):
        store.add(str(tmp_path), "   ")
    with pytest.raises(ValueError):
        store.add(str(tmp_path / "missing"), "do something")


def test_only_queued_tasks_can_be_cancelled(store, tmp_path):
    task = store.add(str(tmp_path), "a")
    assert store.cancel(task.id).status == "cancelled"
    running = store.update(store.add(str(tmp_path), "b").id, status="running")
    with pytest.raises(ValueError):
        store.cancel(running.id)


def test_the_active_task_is_running_or_waiting(store, tmp_path):
    task = store.add(str(tmp_path), "a")
    assert store.active() is None
    store.update(task.id, status="waiting")
    assert store.active().id == task.id


def test_pause_survives_reopening_the_database(tmp_path):
    Store(tmp_path / "q.db").set_paused(True, "usage limit")
    reopened = Store(tmp_path / "q.db")
    assert reopened.paused()
    assert reopened.pause_reason() == "usage limit"


def test_only_known_fields_can_be_updated(store, tmp_path):
    task = store.add(str(tmp_path), "a")
    with pytest.raises(ValueError):
        store.update(task.id, prompt="changed; DROP TABLE tasks")


# These wordings are written from memory of Claude Code's messages, NOT copied from a captured
# screen; when a real limit screen is seen, save it as a fixture and test against it instead.
@pytest.mark.parametrize("text", [
    "5-hour limit reached ∙ resets 3pm",
    "Claude usage limit reached. Your limit will reset at 5pm.",
    "Weekly limit reached ∙ resets Mon 9am",
])
def test_usage_limit_messages_are_recognised(text):
    assert hit_limit(text)


def test_ordinary_text_about_limits_is_not_a_hit_limit():
    assert not hit_limit("● I added a rate limit of 100 requests per minute.")
