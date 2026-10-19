"""The outbox, with a fake slack.sh: these tests never reach Slack."""

import subprocess

import pytest

from ollagi.slack_outbox import Outbox


class FakeHelper:
    def __init__(self, returncode=0):
        self.calls, self.returncode = [], returncode

    def __call__(self, argv, stdin):
        self.calls.append((list(argv), stdin))
        if argv[1] == "preview":
            return subprocess.CompletedProcess(argv, 0, "--- will send:\n" + stdin + "\n--- notifies: Pawan\n", "")
        return subprocess.CompletedProcess(argv, self.returncode, "posted ts=1.2", "" if self.returncode == 0 else "denied")


@pytest.fixture
def setup(tmp_path):
    fake = FakeHelper()
    return Outbox(tmp_path / "q.db", helper=tmp_path / "slack.sh", run=fake), fake


def test_a_draft_is_only_stored_nothing_is_sent(setup):
    box, fake = setup
    box.add("#internal", "hello team")
    assert fake.calls == []


def test_preview_asks_who_is_notified_without_sending(setup):
    box, fake = setup
    d = box.add("#internal", "hello @Pawan")
    assert box.preview(d.id) == "--- notifies: Pawan"
    assert [c[0][1] for c in fake.calls] == ["preview"]


def test_send_posts_the_exact_text_once(setup):
    box, fake = setup
    d = box.add("#internal", "hello team")
    sent = box.send(d.id, "hello team")
    assert sent.status == "sent"
    assert fake.calls[-1] == ([str(box.helper), "post", "#internal", "-"], "hello team")
    with pytest.raises(ValueError):
        box.send(d.id, "hello team")  # never twice


def test_a_confirmation_that_differs_from_the_draft_sends_nothing(setup):
    box, fake = setup
    d = box.add("#internal", "hello team")
    with pytest.raises(ValueError):
        box.send(d.id, "hello team!")
    assert fake.calls == []
    assert box.get(d.id).status == "draft"


def test_a_thread_draft_is_sent_as_a_reply(setup):
    box, fake = setup
    d = box.add("#internal", "done", thread_ts="1792.5")
    box.send(d.id, "done")
    assert fake.calls[-1][0] == [str(box.helper), "reply", "#internal", "1792.5", "-"]


def test_editing_or_discarding_a_sent_draft_is_refused(setup):
    box, _ = setup
    d = box.add("#internal", "x")
    box.send(d.id, "x")
    with pytest.raises(ValueError):
        box.edit(d.id, "y")
    with pytest.raises(ValueError):
        box.discard(d.id)


def test_a_refused_send_stays_a_draft(tmp_path):
    box = Outbox(tmp_path / "q.db", helper=tmp_path / "slack.sh", run=FakeHelper(returncode=1))
    d = box.add("#internal", "x")
    with pytest.raises(RuntimeError):
        box.send(d.id, "x")
    assert box.get(d.id).status == "draft"
