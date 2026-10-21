"""`ollagi serve` runs the web page on 127.0.0.1; `ollagi qr` shows the phone address as a QR code.

When the config file does not say who may connect, Tailscale's own answer is used: the page accepts
this machine's tailnet name as a host, and only the login that owns this machine.
"""

import dataclasses
import shutil
import subprocess
from pathlib import Path

from ollagi import config, tailnet
from ollagi.config import Config


def with_tailnet_defaults(settings: Config, net: tailnet.Tailnet | None) -> Config:
    if net is None:
        return settings
    return dataclasses.replace(
        settings,
        allowed_hosts=settings.allowed_hosts or (net.host,),
        allowed_login=settings.allowed_login or net.login,
    )


def run(args) -> int:
    import uvicorn

    from ollagi.web import create_app

    net = tailnet.read()
    settings = with_tailnet_defaults(config.load(args.config) if args.config else config.load(), net)
    port = args.port or settings.port
    print(f"ollagi page on http://127.0.0.1:{port}")
    if net:
        print(f"tailnet: {net.host}, only {settings.allowed_login} may connect through tailscale serve")
    print(f"RAM watcher: {settings.watcher.action} the heaviest session after {settings.watcher.red_seconds:.0f} s of red")
    app = create_app(settings, run_watcher=True, run_queue=True, phone_url=net.url() if net else None)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def qr(args) -> int:
    net = tailnet.read()
    if net is None:
        print("Tailscale is not running, so there is no phone address.")
        return 1
    url = args.url or net.url(https=True if args.https else None)
    print(url)
    if shutil.which("qrencode"):
        # qrencode draws the code with block characters the terminal can show.
        # utf8 draws with plain block characters; the ansi variants rely on colour codes that
        # some terminals (and Claude Code's ! output) do not show.
        subprocess.run(["qrencode", "-t", "utf8", "-m", "2", url], check=False)
    else:
        print("(install qrencode to see a QR code here)")
    print("Scan it with the phone's camera; the phone must be signed in to the same tailnet.")
    print("No QR above? Open the page on this laptop and press Phone: it shows the same code.")
    return 0


def add_to(subparsers) -> None:
    parser = subparsers.add_parser("serve", help="run the web page on 127.0.0.1")
    parser.add_argument("--port", type=int, help="default: port from the config file, else 8765")
    parser.add_argument("--config", type=Path, help="a config file other than ~/.config/ollagi/config.toml")
    parser.set_defaults(handler=run)

    parser = subparsers.add_parser("qr", help="show the page's tailnet address as a QR code")
    parser.add_argument("--https", action="store_true", help="say https even if tailscale serve does not serve it yet")
    parser.add_argument("--url", help="show this address instead")
    parser.set_defaults(handler=qr)
