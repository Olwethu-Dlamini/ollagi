# 0022: HTTPS for the phone

Date: 2026-10-21

Follows 0007, which served the page on plain http until HTTPS was on for the tailnet.

## Context

Three things I want on the phone only work on a page the browser treats as secure: the microphone
for voice (0020), installing the page as an app, and notifications. Over the tailnet the page was
`http://`, which the browser does not count as secure, although Tailscale already encrypts the
traffic between my devices. I turned on HTTPS certificates for the tailnet in the admin console
(DNS page) on 2026-10-21.

## Decision

- `tailscale serve --bg --https=443 http://127.0.0.1:8765`: Tailscale serves the page on https and
  gets and renews the certificate itself (Let's Encrypt, 90 days at a time).
- Plain http on port 80 is switched off (`tailscale serve --http=80 off`), so the phone cannot end
  up on the old address, where voice does not work.
- ollagi reads `tailscale serve status --json`; when port 443 is served with HTTPS, the phone
  address, the QR code and `ollagi qr` say `https://`. Nothing to configure. `ollagi qr --https`
  still forces it.
- The page itself does not change: it already opens its live terminal with `wss://` on an https page.

## Consequences

- The certificate is published in public Certificate Transparency logs, as every public certificate
  is, so the machine's tailnet name is publicly visible. Only the name: the page is still reachable
  from my tailnet alone, and only for my login.
- A bookmark or QR code for the old `http://` address no longer works; scan the new QR code.

## Checked

2026-10-21, on the laptop:
- `tailscale status --json` showed certificate domains; the https page answered 200 with a valid
  certificate (issuer Let's Encrypt, valid until 2027-01-19); plain http no longer answered;
- after restarting the service, the page's phone address was `https://`;
- headless Chromium at phone size over the https address, on a throwaway `bash` session: the page
  was a secure context, the live terminal connected over `wss://`, and the voice button took the
  speech path (a stand-in recogniser, as headless has no microphone) without the "needs https"
  message; the words went into the box and reached the session after send; no page errors.

On my phone through the tailnet, 2026-10-21: it works on https.
