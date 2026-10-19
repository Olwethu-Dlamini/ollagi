"""Read a Claude Code screen and say what state the session is in.

The only input is the text tmux shows (`capture-pane`), so this works for any session without
hooks or log files. States, most urgent first:

    needs_you  a numbered menu is waiting for an answer (permission, question, plan approval)
    working    the spinner line is showing: "✢ Puzzling… (3m 3s · ↓ 9.2k tokens)"
    done       the prompt box is empty and a turn has finished: "✻ Sautéed for 5s"
    idle       the prompt box is showing, nothing has happened yet
    unknown    none of the above (a shell, another program, a screen we do not recognise)

What each state looks like was learned from real Claude Code screens captured by the Collie project
(MIT licence), kept in tests/fixtures/collie/. The spinner's verb changes every time ("Puzzling",
"Wibbling"), so the patterns match the *shape* of a line, never a particular word.
"""

import re
from dataclasses import dataclass, field

ANSI = re.compile(r"\x1b\[[0-9;:?]*[A-Za-z]")
# "❯ 1. Yes" or "  2. No": an optional pointer, a number, a dot, the label.
OPTION = re.compile(r"^\s*(❯\s*)?(\d{1,2})\.\s+(\S.*?)\s*$")
# "✢ Puzzling… (3m 3s · ↓ 9.2k tokens)": a symbol, a word, an ellipsis, then "(" and a time.
SPINNER = re.compile(r"^\s*\S\s+[\w'’-]+…\s*\(\d")
# "✻ Sautéed for 5s" or "✻ Crunched for 2s · done 7:10 PM": a finished turn.
FINISHED = re.compile(r"^\s*\S\s+[\w'’-]+ for \d+[smh]")
PROMPT_BOX = re.compile(r"^\s*❯")
RULE = re.compile(r"^[\s─━╌═]+$")
LOOK_BACK = 60  # only the bottom of the screen matters for the current state


@dataclass(frozen=True)
class Option:
    number: int
    label: str


@dataclass(frozen=True)
class Reading:
    state: str
    question: str | None = None
    options: list[Option] = field(default_factory=list)


def plain(text: str) -> str:
    """Remove colour codes, so patterns only see the characters."""
    return ANSI.sub("", text)


def read(screen: str) -> Reading:
    lines = [line.rstrip() for line in plain(screen).splitlines()]
    bottom = [line for line in lines if line.strip()][-LOOK_BACK:]

    menu = find_menu(bottom)
    if menu:
        return menu
    if any(SPINNER.match(line) for line in bottom):
        return Reading("working")
    if any(PROMPT_BOX.match(line) for line in bottom):
        return Reading("done" if any(FINISHED.match(line) for line in bottom) else "idle")
    return Reading("unknown")


def find_menu(lines: list[str]) -> Reading | None:
    """A menu is option 1, 2, ... (possibly with description lines between them).

    Start from the LAST "1." line, because older menus that were already answered can still be
    in the scrollback above.
    """
    starts = [i for i, line in enumerate(lines) if (m := OPTION.match(line)) and m.group(2) == "1"]
    if not starts:
        return None
    first = starts[-1]
    options, expected, pointed = [], 1, False
    for line in lines[first:]:
        m = OPTION.match(line)
        if m and int(m.group(2)) == expected:
            options.append(Option(expected, m.group(3)))
            pointed = pointed or bool(m.group(1))
            expected += 1
    # A real menu has at least two choices and the ❯ pointer on one of them. A numbered list in
    # Claude's own answer ("1. Read the config  2. ...") has no pointer.
    if len(options) < 2 or not pointed:
        return None
    return Reading("needs_you", question=find_question(lines[:first]), options=options)


def find_question(above: list[str]) -> str | None:
    """The nearest line above the menu with a question mark, else the nearest real line."""
    candidates = [line.strip() for line in reversed(above[-8:]) if line.strip() and not RULE.match(line)]
    for line in candidates:
        if "?" in line:
            return line
    return candidates[0] if candidates else None
