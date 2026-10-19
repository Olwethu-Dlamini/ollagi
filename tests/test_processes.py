from ollagi.processes import Proc, find_sessions, parse_rss, parse_stat
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
