from ollagi.budget import GIB, Limits
from ollagi.doctor import report
from ollagi.processes import Session
from ollagi.system import MIB, Load, Memory

MEMORY = Memory(total=12 * GIB, available=int(4.5 * GIB), swap_total=2 * GIB, swap_free=GIB)
CALM = Load(one_minute=1.0, five_minutes=1.2, cpus=8)


def test_report_lists_each_session_and_says_yes_when_one_fits():
    text, verdict = report(MEMORY, CALM, [Session(pid=200, tree_rss=400 * MIB, processes=3)], Limits())
    assert verdict.can_start == 1
    assert "pid 200: 400 MiB across 3 processes" in text
    assert "start another? yes: 1 more can start" in text
    assert "swap      1.0 GiB used of 2.0 GiB" in text


def test_report_says_no_when_nothing_fits():
    full = Memory(total=12 * GIB, available=GIB, swap_total=0, swap_free=0)
    text, verdict = report(full, CALM, [], Limits())
    assert verdict.can_start == 0
    assert "start another? no: 0 more can start" in text
