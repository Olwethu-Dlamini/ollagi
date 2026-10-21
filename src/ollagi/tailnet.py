"""What Tailscale knows about this machine: its tailnet name and the login that owns it.

`tailscale status --json` describes the tailnet. Two values matter here:
- `Self.DNSName`, e.g. "laptop.example-tailnet.ts.net." (MagicDNS name; the final dot is DNS notation);
- the login of the user who owns this machine, looked up through `Self.UserID` in `User`.

ollagi uses them as safe defaults: the page accepts its tailnet name as a host, and only the owner's
login when the request comes through `tailscale serve`.

`tailscale serve status --json` says how the page is served. Once HTTPS is on for the tailnet and the
page is served on port 443 (docs/decisions/0022), the phone address is https://, which the phone's
browser needs for the microphone, installing the page as an app, and notifications.
"""

import dataclasses
import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Tailnet:
    host: str  # the machine's MagicDNS name, without the final dot
    login: str  # the owner's Tailscale login
    https: bool = False  # True when `tailscale serve` serves the page over https

    def url(self, https: bool | None = None, port: int | None = None) -> str:
        scheme = "https" if (self.https if https is None else https) else "http"
        return f"{scheme}://{self.host}" + (f":{port}" if port else "")


def parse_status(text: str) -> Tailnet:
    data = json.loads(text)
    me = data["Self"]
    login = data["User"][str(me["UserID"])]["LoginName"]
    return Tailnet(host=me["DNSName"].rstrip("."), login=login)


def parse_serve_status(text: str) -> bool:
    """True when the serve settings include https on port 443."""
    try:
        ports = json.loads(text).get("TCP") or {}
    except (ValueError, AttributeError):
        return False
    return bool((ports.get("443") or {}).get("HTTPS"))


def read() -> Tailnet | None:
    """None when Tailscale is not installed or not running."""
    try:
        result = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    served = subprocess.run(["tailscale", "serve", "status", "--json"], capture_output=True, text=True, timeout=10)
    return dataclasses.replace(parse_status(result.stdout),
                               https=served.returncode == 0 and parse_serve_status(served.stdout))
