"""What Tailscale knows about this machine: its tailnet name and the login that owns it.

`tailscale status --json` describes the tailnet. Two values matter here:
- `Self.DNSName`, e.g. "omarchy.tail653118.ts.net." (MagicDNS name; the final dot is DNS notation);
- the login of the user who owns this machine, looked up through `Self.UserID` in `User`.

ollagi uses them as safe defaults: the page accepts its tailnet name as a host, and only the owner's
login when the request comes through `tailscale serve`.
"""

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Tailnet:
    host: str  # the machine's MagicDNS name, without the final dot
    login: str  # the owner's Tailscale login

    def url(self, https: bool = False, port: int | None = None) -> str:
        scheme = "https" if https else "http"
        return f"{scheme}://{self.host}" + (f":{port}" if port else "")


def parse_status(text: str) -> Tailnet:
    data = json.loads(text)
    me = data["Self"]
    login = data["User"][str(me["UserID"])]["LoginName"]
    return Tailnet(host=me["DNSName"].rstrip("."), login=login)


def read() -> Tailnet | None:
    """None when Tailscale is not installed or not running."""
    try:
        result = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return parse_status(result.stdout)
