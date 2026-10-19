from ollagi.budget import GIB, Limits, how_many_can_start
from ollagi.system import MIB, Load, Memory

CALM = Load(one_minute=1.0, five_minutes=1.0, cpus=8)
LIMITS = Limits(keep_free=int(1.5 * GIB), per_session=int(1.5 * GIB), max_sessions=2)


def memory(available_gib: float) -> Memory:
    return Memory(total=12 * GIB, available=int(available_gib * GIB), swap_total=0, swap_free=0)


def test_an_idle_machine_with_plenty_of_ram_is_capped_by_max_sessions():
    verdict = how_many_can_start(memory(10), CALM, [], LIMITS)
    assert verdict.can_start == 2


def test_memory_left_after_the_reserve_decides_the_count():
    # 4.5 available - 1.5 kept free = 3.0, which fits two sessions of 1.5
    assert how_many_can_start(memory(4.5), CALM, [], LIMITS).can_start == 2
    # 4.4 - 1.5 = 2.9, which fits only one
    assert how_many_can_start(memory(4.4), CALM, [], LIMITS).can_start == 1


def test_a_running_session_keeps_room_to_grow():
    # One session using 400 MiB may still grow by about 1.1 GiB, so that is set aside:
    # 4.5 - 1.5 - 1.1 = 1.9 left, which fits one more, not two.
    # max_sessions is raised to 3 so memory, not the session limit, decides the answer.
    roomy = Limits(keep_free=LIMITS.keep_free, per_session=LIMITS.per_session, max_sessions=3)
    verdict = how_many_can_start(memory(4.5), CALM, [400 * MIB], roomy)
    assert verdict.can_start == 1


def test_no_new_session_when_the_limit_is_reached():
    verdict = how_many_can_start(memory(10), CALM, [400 * MIB, 400 * MIB], LIMITS)
    assert verdict.can_start == 0
    assert "limit is 2" in verdict.reason


def test_no_new_session_when_the_cpus_are_overloaded():
    busy = Load(one_minute=9.5, five_minutes=6.0, cpus=8)
    verdict = how_many_can_start(memory(10), busy, [], LIMITS)
    assert verdict.can_start == 0
    assert "CPU overloaded" in verdict.reason


def test_less_memory_than_the_reserve_never_goes_negative():
    assert how_many_can_start(memory(1.0), CALM, [], LIMITS).can_start == 0
