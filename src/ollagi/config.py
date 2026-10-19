"""Settings, read from ~/.config/ollagi/config.toml (TOML, parsed by the standard library's tomllib).

Everything has a default, so ollagi works with no file at all. Example file:

    port = 8765
    allowed_login = "me@example.com"     # the Tailscale login allowed in through `tailscale serve`
    allowed_hosts = ["laptop.example-tailnet.ts.net"]

    [[projects]]
    name = "simedia"
    directory = "/run/media/oll/Linux/SIMEDIA/DATA!"

    [watcher]                  # the RAM watcher (docs/decisions/0008); every key is optional
    action = "freeze"          # "freeze", "stop" or "warn"
    red_free_gib = 0.75
    amber_free_gib = 1.5
    red_pressure = 30          # percent of time programs waited for memory, last 10 s
    amber_pressure = 10
    red_seconds = 10
    green_seconds = 60

Projects are the folders offered when starting a session. Nothing in the code is tied to one of them,
which is what makes ollagi usable beyond SiMedia.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ollagi.watcher import ACTIONS, GIB, Settings as WatcherSettings

DEFAULT_PATH = Path.home() / ".config" / "ollagi" / "config.toml"


@dataclass(frozen=True)
class Project:
    name: str
    directory: str


@dataclass(frozen=True)
class Config:
    port: int = 8765
    allowed_login: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    projects: tuple[Project, ...] = field(default_factory=tuple)
    watcher: WatcherSettings = field(default_factory=WatcherSettings)


def parse(text: str) -> Config:
    data = tomllib.loads(text)
    return Config(
        port=int(data.get("port", 8765)),
        allowed_login=data.get("allowed_login"),
        allowed_hosts=tuple(data.get("allowed_hosts", ())),
        projects=tuple(Project(p["name"], p["directory"]) for p in data.get("projects", ())),
        watcher=parse_watcher(data.get("watcher", {})),
    )


def parse_watcher(table: dict) -> WatcherSettings:
    default = WatcherSettings()
    action = table.get("action", default.action)
    if action not in ACTIONS:
        raise ValueError(f"[watcher] action must be one of {', '.join(ACTIONS)}, not {action!r}")

    def gib_to_bytes(key: str, default_bytes: int) -> int:
        # Multiply first, round last: rounding 0.75 before multiplying would give 0.
        gib = float(table.get(key, default_bytes / GIB))
        return int(gib * GIB)

    return WatcherSettings(
        action=action,
        red_free=gib_to_bytes("red_free_gib", default.red_free),
        amber_free=gib_to_bytes("amber_free_gib", default.amber_free),
        red_pressure=float(table.get("red_pressure", default.red_pressure)),
        amber_pressure=float(table.get("amber_pressure", default.amber_pressure)),
        red_seconds=float(table.get("red_seconds", default.red_seconds)),
        green_seconds=float(table.get("green_seconds", default.green_seconds)),
    )


def load(path: Path = DEFAULT_PATH) -> Config:
    return parse(path.read_text()) if path.exists() else Config()
