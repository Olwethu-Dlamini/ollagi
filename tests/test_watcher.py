from ollagi.watcher import GIB, Action, SessionState, Settings, Watcher, level
from ollagi.system import MIB

S = Settings(action="freeze", red_seconds=10, green_seconds=60)
PLENTY, SHORT, CRITICAL = 4 * GIB, int(1.2 * GIB), int(0.5 * GIB)


def sessions(*items):
    return [SessionState(name, mib * MIB, frozen) for name, mib, frozen in items]


def test_levels_from_free_memory_and_pressure():
    assert level(PLENTY, 0.0, S) == "green"
    assert level(SHORT, 0.0, S) == "amber"
    assert level(PLENTY, 15.0, S) == "amber"
    assert level(CRITICAL, 0.0, S) == "red"
    assert level(PLENTY, 45.0, S) == "red"


def test_red_must_last_before_anything_is_frozen():
    w = Watcher(S)
    two = sessions(("small", 400, False), ("big", 2000, False))
    assert w.step(0, CRITICAL, 0, two) == []
    assert w.step(9, CRITICAL, 0, two) == []
    assert w.step(10, CRITICAL, 0, two) == [Action("freeze", "big")]


def test_one_session_per_red_period_never_all_at_once():
    w = Watcher(S)
    w.step(0, CRITICAL, 0, sessions(("small", 400, False), ("big", 2000, False)))
    assert w.step(10, CRITICAL, 0, sessions(("small", 400, False), ("big", 2000, False))) == [Action("freeze", "big")]
    after = sessions(("small", 400, False), ("big", 2000, True))
    assert w.step(15, CRITICAL, 0, after) == []  # waits a full red period again
    assert w.step(20, CRITICAL, 0, after) == [Action("freeze", "small")]


def test_a_short_spike_does_nothing():
    w = Watcher(S)
    one = sessions(("big", 2000, False))
    w.step(0, CRITICAL, 0, one)
    w.step(5, PLENTY, 0, one)  # back to green before 10 s
    assert w.step(12, CRITICAL, 0, one) == []  # red restarted at 12, not 0


def test_green_for_long_enough_thaws_one_frozen_session_at_a_time():
    w = Watcher(S)
    w.step(0, CRITICAL, 0, sessions(("a", 900, False), ("b", 800, False)))
    w.step(10, CRITICAL, 0, sessions(("a", 900, False), ("b", 800, False)))  # freezes a
    w.step(20, CRITICAL, 0, sessions(("a", 900, True), ("b", 800, False)))  # freezes b
    frozen = sessions(("a", 900, True), ("b", 800, True))
    w.step(21, PLENTY, 0, frozen)  # green starts
    assert w.step(80, PLENTY, 0, frozen) == []
    assert w.step(81, PLENTY, 0, frozen) == [Action("thaw", "a")]  # frozen first, thawed first
    assert w.step(100, PLENTY, 0, sessions(("a", 900, False), ("b", 800, True))) == []
    assert w.step(141, PLENTY, 0, sessions(("a", 900, False), ("b", 800, True))) == [Action("thaw", "b")]


def test_sessions_frozen_by_hand_are_never_thawed_by_the_watcher():
    w = Watcher(S)
    w.step(0, PLENTY, 0, [])
    assert w.step(500, PLENTY, 0, sessions(("mine", 900, True))) == []


def test_warn_mode_only_writes_an_event_once():
    w = Watcher(Settings(action="warn", red_seconds=10))
    one = sessions(("big", 2000, False))
    w.step(0, CRITICAL, 0, one)
    assert w.step(10, CRITICAL, 0, one) == []
    assert w.step(20, CRITICAL, 0, one) == []
    assert sum("warn only" in e.text for e in w.events) == 1


def test_stop_mode_stops_the_heaviest():
    w = Watcher(Settings(action="stop", red_seconds=10))
    two = sessions(("small", 400, False), ("big", 2000, False))
    w.step(0, CRITICAL, 0, two)
    assert w.step(10, CRITICAL, 0, two) == [Action("stop", "big")]
