# 0006: A FastAPI server on 127.0.0.1, one static page, and three access rules

Date: 2026-10-19

## Context

The interface must work on the laptop and on my phone, show sessions and the system, and let me
type into a Claude session. Typing into a session that may run with broad permissions is powerful,
so who can reach the page matters as much as what it shows.

## Decision

- **FastAPI + uvicorn** (two new dependencies, about 5 MB with what they pull in). FastAPI maps URLs
  to Python functions and turns return values into JSON; uvicorn is the web server that runs it.
  `httpx` is added for tests only (FastAPI's test client uses it).
- **One static HTML page with plain JavaScript** that fetches JSON from `/api/...`. No frontend
  framework and no build step: the page is one file that can be read top to bottom.
- **Listen on 127.0.0.1 only.** Nothing outside the laptop can connect directly. The phone reaches
  it through `tailscale serve` (decision 0007), which forwards to 127.0.0.1.
- **Three checks on every request** (`src/ollagi/access.py`):
  1. the Host header must be `127.0.0.1`, `localhost` or a configured tailnet name (blocks DNS
     rebinding);
  2. a request forwarded by Tailscale carries `Tailscale-User-Login`; if `allowed_login` is set,
     only that login gets in;
  3. any change (POST) must carry `X-Ollagi: 1`, which our page sends and other sites cannot add
     without a CORS preflight this server never approves (blocks cross-site requests).

## Considered

- Python's built-in `http.server`: no dependencies, but routing, JSON and tests would all be
  hand-written, which is more code to explain, not less.
- Passwords or tokens: Tailscale already proves which device and person is connecting; a second
  login adds friction without adding much while the page is never exposed outside the tailnet.
- Running processes as root or managing system services from the page: out of scope for now. The
  page reads the system and manages ollagi's own sessions only.
