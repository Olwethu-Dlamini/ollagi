# 0019: Summaries by Haiku, on request

Date: 2026-10-20

## Context

On the phone, a session's screen is a lot of terminal text to read to find out where it is. I want
a few plain words instead: what it is doing, what it is waiting for, what I could do next. Reading a
screen that way needs a model, and a model spends tokens. From the start I did not want ollagi to
burn tokens on its own (0001), so this must run only when I ask.

Chosen together with an installable app and phone notifications (to follow; both need HTTPS).

## Decision

- The session view gets a **Summary** tab. Opening it costs nothing. Its **Summarise** button sends
  the last 150 lines of the screen (at most 12,000 characters) to `claude -p` with the Haiku model
  and shows the answer with the tokens it took. The prompt asks for at most three short lines, the
  last starting with "Next:"; Haiku sometimes writes two longer paragraphs instead. Never on a
  timer, never for every session at once.
- It runs through the Claude Code CLI on my Claude plan, so it counts toward the plan's limits and
  needs no API key of its own.
- The call is kept small and harmless:
  - `--tools ""`: no tools, so the model can only read what it is given.
  - `--setting-sources ""`, `--strict-mcp-config` and a neutral folder
    (`~/.local/share/ollagi/summaries`): no settings, hooks, MCP servers, CLAUDE.md or project
    memory. My hooks paste large notes into every new Claude session; that would cost tens of
    thousands of tokens per tap. `--bare` would skip them too, but it only accepts an API key.
  - `alwaysThinkingEnabled: false`: the same summary took 16 output tokens instead of 109.
  - `--no-session-persistence`: nothing is saved to resume.
  - The screen goes in inside `<screen>` tags and the system prompt says it is data, so what a
    session printed is described, not obeyed.
- `POST /api/sessions/{name}/summary`. A POST, so the `X-Ollagi` rule stops another website from
  spending my tokens. One summary at a time, so a double tap does not pay twice. Unknown or frozen
  sessions are refused; a failure (a usage limit, a login problem) is shown with its reason.
- `claude -p` writes a session file that says "interactive" like a terminal session does; its
  entrypoint `sdk-cli` (a terminal session says `cli`) keeps it out of "started in a terminal" (0016).

Considered and not chosen: an API key (a separate bill, apart from the plan), and no model at all,
showing Claude's own last message from the conversation file (free, but no suggested next step).

## Consequences

- Measured per press (2026-10-20, sample screen of a permission question): 587 to 605 input tokens,
  87 to 93 output tokens, about 2 s; Claude Code reported $0.001 for each.
- While it runs, one more `claude` process is on the laptop for those seconds (a Claude process is
  185 to 380 MiB, 0018), and the RAM watcher counts it like any Claude process.
- Haiku can misread a screen. The summary is a quick read, not a replacement for the screen.

## Checked

- Unit tests with a fake `claude`: the flags, the screen wrapped as data, only the end of a long
  screen sent, failures that say why, the route's rules (403 without `X-Ollagi`, 404, 409 frozen,
  409 while another runs, 502 with the reason); each rule's test fails without the rule.
- A real call through `summary.py` on a sample screen: it named the failing test and the waiting
  permission question and suggested pressing 1 or 3.
- On the laptop through the restarted service and the tailnet address, at phone size, headless
  Chromium, on a throwaway `bash` session showing a sample permission question: opening the tab sent
  no request; Summarise sent one POST, showed "Asking…" while waiting, then the summary and
  "haiku-4-5 · 587 in, 87 out · 2 s"; no page errors.
