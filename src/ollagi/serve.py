"""`ollagi serve`: run the web page on 127.0.0.1 (the tailnet reaches it through `tailscale serve`)."""

from ollagi import config


def run(args) -> int:
    import uvicorn

    from ollagi.web import create_app

    settings = config.load()
    port = args.port or settings.port
    print(f"ollagi page on http://127.0.0.1:{port}  (only this machine; use `tailscale serve` for the phone)")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    return 0


def add_to(subparsers) -> None:
    parser = subparsers.add_parser("serve", help="run the web page on 127.0.0.1")
    parser.add_argument("--port", type=int, help="default: port from the config file, else 8765")
    parser.set_defaults(handler=run)
