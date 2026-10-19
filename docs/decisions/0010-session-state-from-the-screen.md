# 0010: Tell a session's state from its screen, tested on real Claude screens

Date: 2026-10-19

## Context

The redesigned page (inspired by Collie and Codeman) shows each session with a state dot, red for
"needs you", and turns Claude's permission menus into buttons. That needs the state of every session.

## Decision

`src/ollagi/claude_screen.py` reads the text tmux already gives us:

| State | Recognised by |
|-------|---------------|
| needs_you | numbered options 1, 2, ... with the `❯` pointer on one, and the question above them |
| working | the spinner line's shape: symbol, word, `…`, `(` and a time |
| done | the `❯` prompt box with a finished turn above it (`✻ <word> for 5s`) |
| idle | the prompt box with no finished turn |
| unknown | anything else |

Patterns match the shape of a line, never a word: the spinner verb is random.

Tests run on twelve real Claude Code screens copied from Collie (MIT, `tests/fixtures/collie/`),
so no tokens are spent. Two traps found while writing them, both pinned by tests: the feedback
survey "1: Bad 2: Fine" uses colons and appears while Claude works; and a numbered list in
Claude's own answer is not a menu (it has no `❯` pointer).

## Considered

- Claude Code hooks that report state: exact, but they must be configured in every project and
  only cover sessions started after setup. The screen works for every session as it is.
- Reading Claude's transcript files: richer, but tied to an internal file format that changes.

## Limits

Claude Code's screen changes between versions; a new layout can make a session read as
`unknown`. When that happens, capture the screen into a fixture and add a test.
