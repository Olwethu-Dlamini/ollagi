"""Settings, read from ~/.config/ollagi/config.toml (TOML, parsed by the standard library's tomllib).

Everything has a default, so ollagi works with no file at all. Example file:

    port = 8765
    allowed_login = "me@example.com"     # the Tailscale login allowed in through `tailscale serve`
    allowed_hosts = ["omarchy.tail653118.ts.net"]

    [[projects]]
    name = "simedia"
    directory = "/run/media/oll/Linux/SIMEDIA/DATA!"

Projects are the folders offered when starting a session. Nothing in the code is tied to one of them,
which is what makes ollagi usable beyond SiMedia.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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


def parse(text: str) -> Config:
    data = tomllib.loads(text)
    return Config(
        port=int(data.get("port", 8765)),
        allowed_login=data.get("allowed_login"),
        allowed_hosts=tuple(data.get("allowed_hosts", ())),
        projects=tuple(Project(p["name"], p["directory"]) for p in data.get("projects", ())),
    )


def load(path: Path = DEFAULT_PATH) -> Config:
    return parse(path.read_text()) if path.exists() else Config()
