"""The `ollagi` command line.

Each subcommand is one small function. argparse (in the standard library) turns the words typed in
the terminal into a call to that function, so there is no extra package to learn or install.
"""

import argparse

from ollagi import __version__, doctor, serve, session_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ollagi",
        description="Run Claude Code sessions on this machine without overloading it.",
    )
    parser.add_argument("--version", action="version", version=f"ollagi {__version__}")
    # Each module that provides a subcommand adds itself here, one per step of the build.
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    doctor.add_to(subparsers)
    session_commands.add_to(subparsers)
    serve.add_to(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
