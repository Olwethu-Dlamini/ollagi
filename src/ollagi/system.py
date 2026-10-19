"""Read the machine's memory and load from the Linux /proc files.

/proc is not a real folder on disk: the kernel generates each file when it is read, so reading it is
how a program asks the kernel "how are you doing right now?".

The parse functions take the file's text as an argument instead of opening the file themselves.
That keeps them pure (same input, same output), so tests can feed them sample text without
depending on the machine they run on.
"""

import os
from dataclasses import dataclass
from pathlib import Path

KIB = 1024
MIB = 1024 * KIB


@dataclass(frozen=True)
class Memory:
    """Memory figures in bytes."""

    total: int
    available: int  # what can be used without swapping: free RAM plus cache the kernel can drop
    swap_total: int
    swap_free: int


@dataclass(frozen=True)
class Load:
    """How busy the CPUs are, averaged over the last 1 and 5 minutes."""

    one_minute: float
    five_minutes: float
    cpus: int


def parse_meminfo(text: str) -> Memory:
    """Turn the text of /proc/meminfo into a Memory.

    Each line looks like "MemAvailable:    4512345 kB". The kernel's "kB" means KiB (1024 bytes).
    """
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            values[name.strip()] = int(parts[0]) * KIB
    return Memory(
        total=values["MemTotal"],
        available=values["MemAvailable"],
        swap_total=values.get("SwapTotal", 0),
        swap_free=values.get("SwapFree", 0),
    )


def parse_loadavg(text: str, cpus: int) -> Load:
    """Turn the text of /proc/loadavg into a Load.

    The file looks like "1.90 1.61 2.22 3/1234 56789": the first three numbers are the average
    number of tasks running or waiting for a CPU over 1, 5 and 15 minutes.
    """
    one, five = text.split()[:2]
    return Load(one_minute=float(one), five_minutes=float(five), cpus=cpus)


def read_memory(proc: Path = Path("/proc")) -> Memory:
    return parse_meminfo((proc / "meminfo").read_text())


def read_load(proc: Path = Path("/proc"), cpus: int | None = None) -> Load:
    return parse_loadavg((proc / "loadavg").read_text(), cpus or os.cpu_count() or 1)
