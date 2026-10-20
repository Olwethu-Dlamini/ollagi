"""A live terminal in the browser for a session (docs/decisions/0018).

The page's normal screen view reads the screen every second and a half and types through
`send-keys`. A live terminal is the real thing instead: `tmux attach` for the session runs here in a
pseudo-terminal (a "pty", the kernel's stand-in for a terminal window), and its bytes travel to the
browser and back over a WebSocket. In the browser, xterm.js draws them like any terminal would.

    browser (xterm.js)  <-- WebSocket -->  this server  <-- pty -->  tmux attach  <-->  the session

The page sends small JSON messages: {"type": "input", "data": "..."} for typing, and
{"type": "resize", "rows": R, "cols": C} when its terminal changes size. The server sends the
program's output back as raw bytes.

The program is started through `setsid -c`, which gives it a session of its own with the pty as its
controlling terminal. Only then does the kernel tell it (SIGWINCH) that the terminal was resized.
Its environment carries OLLAGI_VIEWER=browser, so desktop.py does not count it as a laptop window.
"""

import asyncio
import fcntl
import json
import math
import os
import select
import struct
import subprocess
import termios
from collections.abc import Sequence
from dataclasses import dataclass

import anyio

from ollagi import sessions

MAX_ROWS = 300
MAX_COLS = 500
TERM = "xterm-256color"  # what xterm.js understands


@dataclass(frozen=True)
class Input:
    data: str


@dataclass(frozen=True)
class Resize:
    rows: int
    cols: int


def valid_size(rows, cols) -> bool:
    return (type(rows) is int and type(cols) is int  # not bool, not "40"
            and 1 <= rows <= MAX_ROWS and 1 <= cols <= MAX_COLS)


def parse(message: str) -> Input | Resize:
    """One message from the page. Anything that is not exactly typing or a resize is refused."""
    try:
        data = json.loads(message)
    except ValueError as error:
        raise ValueError("not JSON") from error
    if not isinstance(data, dict):
        raise ValueError("expected an object")
    if data.get("type") == "input" and isinstance(data.get("data"), str):
        return Input(data["data"])
    if data.get("type") == "resize" and valid_size(data.get("rows"), data.get("cols")):
        return Resize(data["rows"], data["cols"])
    raise ValueError("expected an input or a resize message")


def session_command(name: str) -> list[str]:
    """What runs in the pty for a session: tmux attached to it, like a window on the laptop."""
    return sessions.attach_command(name)


def set_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def size(fd: int) -> tuple[int, int]:
    rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    return rows, cols


class Terminal:
    """A program running in a pty. `fd` is our end of it: what we write there, the program reads as
    typing; what the program prints, we read from it."""

    def __init__(self, argv: Sequence[str], rows: int, cols: int):
        if not valid_size(rows, cols):
            raise ValueError(f"terminal size out of range: {rows}x{cols}")
        ours, theirs = os.openpty()
        set_size(theirs, rows, cols)
        environ = {**os.environ, "TERM": TERM, "OLLAGI_VIEWER": "browser"}
        environ.pop("TMUX", None)  # tmux refuses to attach from "inside" another tmux
        try:
            self.process = subprocess.Popen(["setsid", "-c", *argv], stdin=theirs, stdout=theirs, stderr=theirs,
                                            env=environ, close_fds=True)
        finally:
            os.close(theirs)  # the program has its own copy; ours would keep the pty open after it ends
        os.set_blocking(ours, False)
        self.fd = ours

    def read(self) -> bytes:
        """What the program printed since the last read (b"" if nothing). Raises EOFError once the
        program has ended and the pty is closed."""
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return b""
        except OSError as error:  # Linux answers EIO when the other end of the pty is closed
            raise EOFError from error
        if not data:
            raise EOFError
        return data

    def write(self, data: bytes) -> None:
        while data:
            try:
                data = data[os.write(self.fd, data):]
            except BlockingIOError:
                select.select([], [self.fd], [], 1)  # the pty is full: wait until the program reads

    def resize(self, rows: int, cols: int) -> None:
        """The kernel stores the new size on the pty and signals the program, which redraws."""
        set_size(self.fd, rows, cols)

    def close(self) -> None:
        """Closing our end hangs up the pty, which ends `tmux attach`: the session itself keeps running."""
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


async def relay(websocket, term: Terminal) -> None:
    """Pass bytes between the browser and the program until either side ends.

    The event loop watches the pty and calls `readable` when there is output. Output goes through a
    stream to a single sender, so it reaches the browser in the order it was printed. The two
    directions run in one anyio task group (the same library Starlette uses), so when one ends, the
    other is cancelled cleanly; closing the pty is shielded so it happens even then."""
    loop = asyncio.get_running_loop()
    outgoing, output = anyio.create_memory_object_stream(math.inf)
    program_ended = False

    def readable():
        try:
            data = term.read()
        except EOFError:
            loop.remove_reader(term.fd)
            outgoing.send_nowait(None)  # the program ended
            return
        if data:
            outgoing.send_nowait(data)

    async def send_output(group):
        nonlocal program_ended
        async for data in output:
            if data is None:
                break
            await websocket.send_bytes(data)
        program_ended = True
        group.cancel_scope.cancel()

    async def receive_input(group):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                group.cancel_scope.cancel()
                return
            try:
                parsed = parse(message.get("text") or "")
            except ValueError:
                continue  # a bad message is ignored, not fatal
            if isinstance(parsed, Input):
                term.write(parsed.data.encode())
            else:
                term.resize(parsed.rows, parsed.cols)

    loop.add_reader(term.fd, readable)
    try:
        async with outgoing, output, anyio.create_task_group() as group:
            group.start_soon(send_output, group)
            group.start_soon(receive_input, group)
    finally:
        loop.remove_reader(term.fd)
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(term.close)
    if program_ended:  # tmux detached or the session stopped: tell the page
        await websocket.close(code=1000, reason="the terminal ended")
