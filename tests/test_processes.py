from ollagi.processes import Proc, Session, find_sessions, parse_rss, parse_stat
from ollagi.system import MIB


def test_stat_name_may_contain_brackets_and_spaces():
    name, ppid = parse_stat("4242 (Web Content (x)) S 1700 4242 4242 0 -1 4194560")
    assert name == "Web Content (x)"
    assert ppid == 1700


def test_rss_is_read_from_the_vmrss_line():
    assert parse_rss("Name:\tclaude\nVmRSS:\t  388096 kB\nThreads:\t12\n") == 388096 * 1024


def test_kernel_threads_without_vmrss_count_as_zero():
    assert parse_rss("Name:\tkworker/0:1\nThreads:\t1\n") == 0


def test_a_session_counts_its_whole_tree():
    procs = [
        Proc(pid=1, ppid=0, name="systemd", rss=10 * MIB),
        Proc(pid=100, ppid=1, name="bash", rss=5 * MIB),
        Proc(pid=200, ppid=100, name="claude", rss=380 * MIB),
        Proc(pid=300, ppid=200, name="bash", rss=4 * MIB),
        Proc(pid=301, ppid=300, name="dotnet", rss=900 * MIB),
    ]
    [session] = find_sessions(procs)
    assert session.pid == 200
    assert session.tree_rss == (380 + 4 + 900) * MIB
    assert session.processes == 3


def test_a_claude_started_by_claude_belongs_to_the_outer_session():
    procs = [
        Proc(pid=200, ppid=1, name="claude", rss=380 * MIB),
        Proc(pid=210, ppid=200, name="claude", rss=150 * MIB),
    ]
    [session] = find_sessions(procs)
    assert session.pid == 200
    assert session.tree_rss == 530 * MIB


def test_two_separate_sessions_are_counted_separately():
    procs = [
        Proc(pid=200, ppid=1, name="claude", rss=380 * MIB),
        Proc(pid=500, ppid=1, name="claude", rss=330 * MIB),
    ]
    assert [s.pid for s in find_sessions(procs)] == [200, 500]


def test_an_omp_session_counts_its_whole_tree_like_a_claude_session():
    # docs/decisions/0035: the RAM watcher and the budget must see omp's builds and tests too.
    procs = [
        Proc(pid=1, ppid=0, name="systemd", rss=10 * MIB),
        Proc(pid=400, ppid=1, name="omp", rss=420 * MIB),
        Proc(pid=410, ppid=400, name="bash", rss=4 * MIB),
        Proc(pid=411, ppid=410, name="dotnet", rss=900 * MIB),
    ]
    assert find_sessions(procs) == [Session(pid=400, tree_rss=1324 * MIB, processes=3)]


def test_omps_background_helpers_are_not_sessions_of_their_own():
    # Seen on this laptop: `omp daemon brok` (a worker daemon; the kernel cuts names at 15 characters).
    procs = [
        Proc(pid=1, ppid=0, name="systemd", rss=10 * MIB),
        Proc(pid=34778, ppid=1, name="omp daemon brok", rss=60 * MIB),
    ]
    assert find_sessions(procs) == []


def test_a_claude_run_by_omp_belongs_to_the_omp_session():
    procs = [
        Proc(pid=400, ppid=1, name="omp", rss=420 * MIB),
        Proc(pid=450, ppid=400, name="claude", rss=330 * MIB),
    ]
    assert find_sessions(procs) == [Session(pid=400, tree_rss=750 * MIB, processes=2)]
