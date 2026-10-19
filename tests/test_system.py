from ollagi.system import KIB, parse_loadavg, parse_meminfo, parse_mounts, parse_pressure

# A shortened copy of this laptop's /proc/meminfo (2026-10-19). Real files have about 50 lines;
# only the ones ollagi reads matter here.
MEMINFO = """\
MemTotal:       11923456 kB
MemFree:          357376 kB
MemAvailable:    4508672 kB
Buffers:            1024 kB
Cached:          5242880 kB
SwapTotal:      23855104 kB
SwapFree:       21862400 kB
HugePages_Total:       0
"""


def test_meminfo_is_read_in_bytes():
    memory = parse_meminfo(MEMINFO)
    assert memory.total == 11923456 * KIB
    assert memory.available == 4508672 * KIB
    assert memory.swap_total == 23855104 * KIB
    assert memory.swap_free == 21862400 * KIB


def test_a_machine_without_swap_reads_zero_swap():
    memory = parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 500 kB\n")
    assert memory.swap_total == 0
    assert memory.swap_free == 0


def test_loadavg_keeps_the_one_and_five_minute_averages():
    load = parse_loadavg("1.90 1.61 2.22 3/1234 56789\n", cpus=8)
    assert load.one_minute == 1.90
    assert load.five_minutes == 1.61
    assert load.cpus == 8


def test_pressure_reads_the_some_line():
    text = "some avg10=12.50 avg60=3.10 avg300=0.80 total=100\nfull avg10=1.00 avg60=0.20 avg300=0.05 total=10\n"
    pressure = parse_pressure(text)
    assert pressure.some_avg10 == 12.5
    assert pressure.some_avg60 == 3.1


def test_mounts_keep_real_disks_once_and_decode_spaces():
    text = """\
/dev/mapper/root / btrfs rw 0 0
proc /proc proc rw 0 0
/dev/mapper/root /home btrfs rw 0 0
tmpfs /tmp tmpfs rw 0 0
/dev/sda4 /run/media/oll/My\\040Disk ntfs3 rw 0 0
"""
    assert parse_mounts(text) == ["/", "/run/media/oll/My Disk"]
