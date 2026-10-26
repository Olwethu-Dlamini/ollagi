"""Settings, read from ~/.config/ollagi/config.toml (TOML, parsed by the standard library's tomllib).

Everything has a default, so ollagi works with no file at all. Example file:

    port = 8765
    allowed_login = "me@example.com"     # the Tailscale login allowed in through `tailscale serve`
    allowed_hosts = ["laptop.example-tailnet.ts.net"]
    agent = "omp"                        # what a new session runs: "claude" (the default) or "omp"

    [[projects]]
    name = "simedia"
    directory = "/run/media/oll/Linux/SIMEDIA/DATA!"
    agent = "claude"                     # optional: this project's sessions run a different agent

    [slack]
    drafts_to = "#my-notes"    # optional: queue events become DRAFTS here; nothing is sent without me

    [desktop]                  # windows on this laptop (docs/decisions/0017); every key is optional
    open_on_start = true       # a session started from the page or `ollagi start` opens a window
    terminal = ["foot", "-T", "ollagi: {name}"]   # {name} becomes the session name

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

from ollagi import agents
from ollagi.desktop import Settings as DesktopSettings
from ollagi.watcher import ACTIONS, GIB, Settings as WatcherSettings

DEFAULT_PATH = Path.home() / ".config" / "ollagi" / "config.toml"


@dataclass(frozen=True)
class Project:
    name: str
    directory: str
    agent: str | None = None  # None: the config's default agent


@dataclass(frozen=True)
class Config:
    port: int = 8765
    allowed_login: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    projects: tuple[Project, ...] = field(default_factory=tuple)
    watcher: WatcherSettings = field(default_factory=WatcherSettings)
    slack_drafts_to: str | None = None
    desktop: DesktopSettings = field(default_factory=DesktopSettings)
    agent: str = agents.DEFAULT

    def agent_for(self, directory: str) -> agents.Agent:
        """The agent a session in `directory` runs: the project's own choice, else the default."""
        for project in self.projects:
            if project.agent and Path(project.directory) == Path(directory):
                return agents.get(project.agent)
        return agents.get(self.agent)


def parse(text: str) -> Config:
    data = tomllib.loads(text)
    projects = tuple(Project(p["name"], p["directory"], p.get("agent")) for p in data.get("projects", ()))
    # An unknown agent is refused when the file is read, not later when a session would start.
    for name in [data.get("agent", agents.DEFAULT), *(p.agent for p in projects if p.agent)]:
        agents.get(name)
    return Config(
        port=int(data.get("port", 8765)),
        allowed_login=data.get("allowed_login"),
        allowed_hosts=tuple(data.get("allowed_hosts", ())),
        projects=projects,
        watcher=parse_watcher(data.get("watcher", {})),
        slack_drafts_to=data.get("slack", {}).get("drafts_to"),
        desktop=parse_desktop(data.get("desktop", {})),
        agent=data.get("agent", agents.DEFAULT),
    )


def parse_desktop(table: dict) -> DesktopSettings:
    default = DesktopSettings()
    terminal = tuple(table.get("terminal", default.terminal))
    if not terminal or not all(isinstance(part, str) and part for part in terminal):
        raise ValueError("[desktop] terminal must be a list of words, for example [\"foot\"]")
    return DesktopSettings(open_on_start=bool(table.get("open_on_start", default.open_on_start)), terminal=terminal)


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
