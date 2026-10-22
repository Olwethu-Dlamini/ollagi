import time

from cryptography.hazmat.primitives.asymmetric import ec

from ollagi import notify, webpush
from ollagi.notify import Notice, SessionWatch


def settle(watch, states, reads=notify.SETTLE_READS):
    """Read the same states as many times as it takes for them to count."""
    found = []
    for _ in range(reads):
        found += watch.update(states)
    return found


def test_nothing_is_said_about_sessions_seen_for_the_first_time():
    # When the server starts, every session already has a state; none of that is news.
    watch = SessionWatch()
    assert settle(watch, {"api": ("needs_you", "Allow edit?"), "web": ("done", None)}) == []


def test_a_question_is_announced_once_with_the_question():
    watch = SessionWatch()
    settle(watch, {"api": ("working", None)})
    found = settle(watch, {"api": ("needs_you", "Do you want to make this edit?")})
    # Urgent: the phone keeps a question on screen until it is answered or dismissed.
    assert found == [Notice("api needs you", "Do you want to make this edit?", "session-api", "/?session=api", urgent=True)]


def test_a_yes_or_no_question_gets_allow_and_deny_buttons():
    from ollagi.claude_screen import Option

    permission = [Option(1, "Yes"), Option(2, "Yes, and don’t ask again for: mkfifo fixture-fifo *"), Option(3, "No")]
    assert notify.answer_buttons(permission) == (("1", "Yes"), ("3", "No"))
    trust = [Option(1, "Yes, I trust this folder"), Option(2, "No, exit")]
    assert notify.answer_buttons(trust) == (("1", "Yes, I trust this folder"), ("2", "No, exit"))
    # A plan's menu has no plain No, and a pick-a-colour menu no Yes: those need the screen.
    plan = [Option(1, "Yes, and use auto mode"), Option(2, "Yes, manually approve edits"), Option(4, "Tell Claude what to change")]
    assert notify.answer_buttons(plan) == ()
    assert notify.answer_buttons([Option(1, "Red"), Option(2, "Green")]) == ()
    assert notify.answer_buttons([]) == ()
    # The buttons travel with the notice, and the readings may carry the options as a third item.
    watch = SessionWatch()
    settle(watch, {"api": ("working", None)})
    found = settle(watch, {"api": ("needs_you", "Do you want to proceed?", permission)})
    assert found[0].actions == (("1", "Yes"), ("3", "No"))
    assert settle(watch, {"api": ("needs_you", "Do you want to make this edit?")}) == []


def test_a_finished_turn_is_announced_only_after_working():
    watch = SessionWatch()
    settle(watch, {"api": ("working", None)})
    assert settle(watch, {"api": ("done", None)}) == [Notice("api finished", "Claude's turn ended.", "session-api", "/?session=api")]
    # idle -> done is not a finished turn (it is how a session looks once the screen is cleared).
    watch = SessionWatch()
    settle(watch, {"web": ("idle", None)})
    assert settle(watch, {"web": ("done", None)}) == []


def test_a_state_seen_for_one_read_only_does_not_count():
    # Between two tool calls the spinner can be gone for a moment, and an older "✻ Worked for 3s"
    # line is still on the screen: for one read the session looks done. That must not buzz the phone.
    watch = SessionWatch()
    settle(watch, {"api": ("working", None)})
    assert watch.update({"api": ("done", None)}) == []
    assert settle(watch, {"api": ("working", None)}) == []


def test_queue_sessions_are_left_to_the_queue():
    # The queue announces its own tasks (done, waiting for you, failed); its sessions are named q<id>.
    watch = SessionWatch()
    settle(watch, {"q7": ("working", None)})
    assert settle(watch, {"q7": ("needs_you", "Allow?")}) == []


def test_a_session_that_goes_away_and_comes_back_starts_fresh():
    watch = SessionWatch()
    settle(watch, {"api": ("working", None)})
    settle(watch, {})
    assert settle(watch, {"api": ("needs_you", "Allow?")}) == []


def test_queue_events_worth_a_notice():
    assert notify.queue_notice("task 3 done") == Notice("Queue", "task 3 done", "queue", "/?view=queue")
    assert notify.queue_notice("task 3 is waiting for you: Allow?").body == "task 3 is waiting for you: Allow?"
    assert notify.queue_notice("task 3 failed: its session ended") is not None
    assert notify.queue_notice("task 3 could not start: no folder") is not None
    assert notify.queue_notice("task 3 hit a usage limit; queue paused") is not None
    assert notify.queue_notice("task 3 started as session q3") is None


def test_watcher_actions_become_notices():
    assert notify.watcher_notice("freeze", "api") == Notice("Memory low", "Paused api to free memory.", "watcher", "/?session=api")
    assert notify.watcher_notice("freeze", "api").urgent is False
    assert notify.watcher_notice("stop", "api").body == "Stopped api to free memory."
    assert notify.watcher_notice("thaw", "api").body == "Memory is back; api continues."


def phone():
    key = ec.generate_private_key(ec.SECP256R1())
    sub = webpush.Subscription(f"https://fcm.googleapis.com/fcm/send/{time.time_ns()}",
                               webpush.b64(webpush.public_bytes(key.public_key())), webpush.b64(b"0123456789abcdef"))
    return sub, key


def test_subscriptions_are_kept_once_per_endpoint(tmp_path):
    store = notify.Subscribers(tmp_path / "push.db")
    sub, _ = phone()
    store.add(sub)
    store.add(sub)  # the page subscribes again on every visit; that must not add a second row
    assert store.all() == [sub]
    store.remove(sub.endpoint)
    assert store.all() == []
    assert (tmp_path / "push.db").stat().st_mode & 0o777 == 0o600


def test_subscribers_refuse_what_is_not_a_browser_subscription(tmp_path):
    store = notify.Subscribers(tmp_path / "push.db")
    sub, _ = phone()
    for bad in (webpush.Subscription("https://example.com/x", sub.p256dh, sub.auth),
                webpush.Subscription(sub.endpoint, webpush.b64(b"short"), sub.auth),
                webpush.Subscription(sub.endpoint, sub.p256dh, webpush.b64(b"short"))):
        try:
            store.add(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    assert store.all() == []


def test_a_notice_reaches_every_phone_and_a_forgotten_one_is_dropped(tmp_path):
    store = notify.Subscribers(tmp_path / "push.db")
    (kept, kept_key), (gone, _) = phone(), phone()
    store.add(kept)
    store.add(gone)
    sent = []

    def send(sub, message, key, now):
        if sub == gone:
            raise webpush.Gone(sub.endpoint)
        sent.append((sub, message))

    notifier = notify.Notifier(store, ec.generate_private_key(ec.SECP256R1()), send=send)
    result = notifier.deliver(Notice("api needs you", "Allow?", "session-api", "/?session=api"))
    assert result == {"sent": 1, "failed": []}
    assert sent == [(kept, {"title": "api needs you", "body": "Allow?", "tag": "session-api", "url": "/?session=api",
                            "urgent": False, "actions": []})]
    assert store.all() == [kept]


def test_a_failed_send_is_reported_and_the_phone_is_kept(tmp_path):
    store = notify.Subscribers(tmp_path / "push.db")
    sub, _ = phone()
    store.add(sub)

    def send(sub, message, key, now):
        raise OSError("network is unreachable")

    notifier = notify.Notifier(store, ec.generate_private_key(ec.SECP256R1()), send=send)
    result = notifier.deliver(Notice("t", "b", "x", "/"))
    assert result["sent"] == 0 and "network is unreachable" in result["failed"][0]
    assert store.all() == [sub]
    assert "network is unreachable" in notifier.events[-1]["text"]


def test_a_long_question_is_cut_to_fit_one_message(tmp_path):
    store = notify.Subscribers(tmp_path / "push.db")
    sub, _ = phone()
    store.add(sub)
    sent = []
    notifier = notify.Notifier(store, ec.generate_private_key(ec.SECP256R1()),
                               send=lambda sub, message, key, now: sent.append(message))
    notifier.deliver(Notice("api needs you", "x" * 10_000, "session-api", "/?session=api"))
    assert len(sent[0]["body"]) <= notify.MAX_BODY
