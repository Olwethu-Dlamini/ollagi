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
"""

from dataclasses import dataclass

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
