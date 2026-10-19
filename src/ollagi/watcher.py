"""The RAM watcher: read memory every few seconds and act before the machine stalls.

Each reading gets a level (docs/decisions/0008 explains the numbers):

    green  enough free memory and little pressure
    amber  under `amber_free` available, or pressure over `amber_pressure` %: no new sessions
    red    under `red_free` available, or pressure over `red_pressure` %

"Pressure" is the share of the last 10 seconds that some program spent waiting for memory
(/proc/pressure/memory). It rises when the machine is already struggling, even if free memory
looks acceptable.

When red has lasted `red_seconds`, the watcher acts on the heaviest ollagi session that is not
frozen yet: `freeze` it (pause, nothing lost), `stop` it, or only `warn`. One session per red
period, so it never freezes everything at once. When green has lasted `green_seconds`, it thaws one
session it froze itself, then waits again before the next. Sessions it did not freeze, and processes
outside ollagi, are never touched.

`Watcher.step` only decides; it returns actions. `run_forever` reads the machine, calls step and
carries the actions out. That split is what lets the tests check every decision without a machine.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from ollagi.system import MIB

GIB = 1024 * MIB
ACTIONS = ("freeze", "stop", "warn")


@dataclass(frozen=True)
class Settings:
    action: str = "freeze"
    amber_free: int = int(1.5 * GIB)
    red_free: int = int(0.75 * GIB)
    amber_pressure: float = 10.0
    red_pressure: float = 30.0
    red_seconds: float = 10.0
    green_seconds: float = 60.0


@dataclass(frozen=True)
class SessionState:
    name: str
    memory: int  # bytes used now
    frozen: bool


@dataclass(frozen=True)
class Action:
    kind: str  # "freeze", "stop" or "thaw"
    name: str


@dataclass
class Event:
    time: float
    text: str


def level(available: int, pressure: float, s: Settings) -> str:
    if available < s.red_free or pressure > s.red_pressure:
        return "red"
    if available < s.amber_free or pressure > s.amber_pressure:
        return "amber"
    return "green"


@dataclass
class Watcher:
    settings: Settings = field(default_factory=Settings)
    level: str = "green"
    since: float = 0.0  # when the current level started, or when the watcher last acted
    frozen_by_me: list[str] = field(default_factory=list)
    events: deque = field(default_factory=lambda: deque(maxlen=50))
    warned: bool = False

    def note(self, now: float, text: str) -> None:
        self.events.append(Event(now, text))

    def step(self, now: float, available: int, pressure: float, sessions: list[SessionState]) -> list[Action]:
        s = self.settings
        current = level(available, pressure, s)
        if current != self.level:
            self.note(now, f"{self.level} -> {current}: {available / GIB:.1f} GiB available, pressure {pressure:.1f}%")
            self.level, self.since, self.warned = current, now, False

        # Forget sessions that were stopped or thawed by hand.
        live = {x.name: x for x in sessions}
        self.frozen_by_me = [n for n in self.frozen_by_me if n in live and live[n].frozen]

        if current == "red" and now - self.since >= s.red_seconds:
            running = [x for x in sessions if not x.frozen]
            if not running:
                return []
            heaviest = max(running, key=lambda x: x.memory)
            self.since = now  # wait a full red period again before touching another session
            if s.action == "warn":
                if not self.warned:
                    self.note(now, f"red: {heaviest.name} is the heaviest ({heaviest.memory / MIB:.0f} MiB); warn only")
                    self.warned = True
                return []
            self.note(now, f"red for {s.red_seconds:.0f} s: {s.action} {heaviest.name} ({heaviest.memory / MIB:.0f} MiB)")
            if s.action == "freeze":
                self.frozen_by_me.append(heaviest.name)
            return [Action(s.action, heaviest.name)]

        if current == "green" and self.frozen_by_me and now - self.since >= s.green_seconds:
            name = self.frozen_by_me.pop(0)  # the one frozen longest ago goes first
            self.since = now
            self.note(now, f"green for {s.green_seconds:.0f} s: thaw {name}")
            return [Action("thaw", name)]

        return []


def run_forever(
    watcher: Watcher,
    read: Callable[[], tuple[int, float, list[SessionState]]],
    act: Callable[[Action], None],
    stop: threading.Event,
    interval: float = 2.0,
) -> None:
    """Read, decide and act every `interval` seconds until `stop` is set. Errors are noted, not fatal."""
    while not stop.is_set():
        now = time.time()
        try:
            available, pressure, sessions = read()
            for action in watcher.step(now, available, pressure, sessions):
                act(action)
        except Exception as error:  # a watcher that dies silently is worse than one that complains
            watcher.note(now, f"watcher error: {error}")
        stop.wait(interval)
