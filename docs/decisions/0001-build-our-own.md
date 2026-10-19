# 0001: Build our own instead of installing an existing tool

Date: 2026-10-19

## Context

I want to run Claude Code sessions on my laptop, watch and answer them from my phone, queue work for
when I am away, and batch similar tickets. Several open-source projects already do parts of this
(researched on GitHub, 2026-10-19):

- Codeman (MIT, TypeScript): tmux-backed sessions, Tailscale HTTPS, single-use QR pairing, overnight
  auto-continue. Very large (about 230 HTTP handlers) and allows up to 20 parallel sessions.
- Collie (MIT, TypeScript + Bun): a phone web app (PWA) that drives agents in tmux over
  `tailscale serve`, with push alerts. Phone control only.
- Agent of Empires (MIT, Rust): many agents in tmux, terminal and web dashboard. No queue.
- CloudCLI / claudecodeui (AGPL): a full web UI, heavy.

## Decision

Build ollagi ourselves, small, reusing the building blocks those projects agree on:

1. tmux keeps each session alive when no one is looking.
2. `tailscale serve` gives HTTPS and tells the app who is connecting, so the page is never public.
3. The phone just opens a web page; pairing is a QR code of its address.

## Why

- Learning: I need to be able to explain every part. A tool with hundreds of handlers is not
  something I can explain; one I built step by step is.
- My hardware: 4 cores, 11 GiB RAM. Running several sessions at once has killed this machine before.
  None of the tools above decides "is there room for another session?" from free memory.
- My work: none of them knows Jira or groups similar tickets.

## Consequences

- Slower to get the first useful version than installing Codeman.
- When a problem is already solved well in one of those projects, read how they did it first.
