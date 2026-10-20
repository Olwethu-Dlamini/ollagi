"""Who may use the web page, decided per request (docs/decisions/0006).

The server listens on 127.0.0.1 only, so the outside world cannot reach it at all. Two ways in:

1. From this machine: a browser on the laptop opens http://127.0.0.1:<port>.
2. From the tailnet: `tailscale serve` receives the request on the machine's tailnet address and
   forwards it to 127.0.0.1. On the way it adds a `Tailscale-User-Login` header naming the person
   whose device sent it. If `allowed_login` is set, only that person gets in.

Two browser tricks are blocked because the page can press keys in a Claude session:

- DNS rebinding: a website makes its own name point at 127.0.0.1 to reach local servers. Its
  requests carry its own name in the Host header, so only known host names are accepted.
- Cross-site requests (CSRF): another site's page could make my browser send a POST here. Every
  change must carry the `X-Ollagi: 1` header. A browser will not add a custom header to a cross-site
  request without asking the server first (a "preflight"), and this server never says yes.

A live terminal (docs/decisions/0018) is a WebSocket, and a browser opens a WebSocket to any
address without a preflight, so the header trick does not protect it. Instead the browser always
says which page opened it, in the `Origin` header, and a website cannot change that. A terminal is
only opened for a page served from the very address it connects to.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

CHANGE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


def check(method: str, headers: dict[str, str], allowed_login: str | None, allowed_hosts: tuple[str, ...]) -> Decision:
    """`headers` must have lowercase names (as HTTP frameworks provide them)."""
    host = headers.get("host", "").rsplit(":", 1)[0].lower()
    if host not in LOCAL_HOSTS and host not in {h.lower() for h in allowed_hosts}:
        return Decision(False, f"unknown host name: {host or '(none)'}")

    login = headers.get("tailscale-user-login")
    if login is not None and allowed_login is not None and login != allowed_login:
        return Decision(False, f"tailscale user {login} is not allowed")

    if method.upper() in CHANGE_METHODS and headers.get("x-ollagi") != "1":
        return Decision(False, "changes must come from the ollagi page (missing X-Ollagi header)")

    return Decision(True)


def check_terminal(headers: dict[str, str], allowed_login: str | None, allowed_hosts: tuple[str, ...]) -> Decision:
    """The rules for opening a live terminal: the same host and Tailscale rules as any request, and
    the page that asks must come from the same address (`Origin` equals `Host`)."""
    decision = check("GET", headers, allowed_login, allowed_hosts)
    if not decision.allowed:
        return decision
    origin = headers.get("origin")
    if not origin:
        return Decision(False, "a terminal needs an origin header (only the ollagi page may open one)")
    if urlsplit(origin).netloc.lower() != headers.get("host", "").lower():
        return Decision(False, f"a terminal may only be opened by the ollagi page, not by {origin}")
    return Decision(True)
