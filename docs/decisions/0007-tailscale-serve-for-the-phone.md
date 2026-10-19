# 0007: Reach the page from the phone with `tailscale serve`

Date: 2026-10-19

## Context

The page listens on 127.0.0.1 (0006), so only the laptop can open it. My phone and laptop are both
on my tailnet (Tailscale's private network between my own devices). This laptop's tailnet name is
`omarchy.tail653118.ts.net`. HTTPS certificates are not enabled for the tailnet yet
(`tailscale status --json` shows no `CertDomains`).

## Decision

- `tailscale serve --bg --http=80 http://127.0.0.1:8765`: Tailscale listens on the laptop's
  tailnet address, port 80, and forwards each request to the page. `--bg` keeps that setting
  after the command exits, and across reboots, until `tailscale serve reset`.
- Plain HTTP for now. Traffic between tailnet devices already travels inside Tailscale's encrypted
  WireGuard tunnel, so "http" here is not readable on the Wi-Fi. Turning on HTTPS for the tailnet
  (admin console, DNS page) later gives a real certificate and lets the browser treat the page as
  secure; then `tailscale serve --bg 8765` serves it on https.
- Tailscale adds `Tailscale-User-Login` to every forwarded request. With no config file, ollagi
  accepts only the login that owns this laptop (read from `tailscale status --json`).
- `ollagi qr` prints the address as a QR code, so the phone opens it by pointing its camera.
- The web server runs as a systemd user service (`deploy/ollagi.service`), so it is there whenever
  I am logged in, and restarting it never stops a Claude session.

## Considered

- `tailscale funnel`: publishes to the whole internet. Never for this page.
- Binding the server to the tailnet IP directly: works, but loses the identity header and would
  need its own login.
- One-time QR tokens (as Codeman does): useful when the network is not private; here Tailscale
  already decides which devices can connect at all.

## Setup, once

`tailscale serve` needs operator rights: `sudo tailscale set --operator=$USER`, after which no sudo
is needed for serve commands.
