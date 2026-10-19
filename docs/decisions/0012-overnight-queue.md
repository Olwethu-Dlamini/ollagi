# 0012: An overnight queue that runs one task at a time

Date: 2026-10-19

## Context

I want to leave the laptop working on tasks while I am away, without it falling over and without
burning through my subscription by starting many sessions at once.

## Decision

- A task is a folder and a prompt, kept in SQLite (`~/.local/share/ollagi/queue.db`).
- The server's queue thread checks every 5 seconds. With no active task, the queue not paused, the
  RAM watcher green and the budget rule saying a session fits, it starts the next task as session
  `q<id>` running `claude "<prompt>"`: an ordinary session, visible and answerable from the phone.
- **One task at a time**, always. It costs the same subscription usage as doing the tasks by hand,
  spread over the night instead of all at once.
- The task's state comes from its screen (decision 0010):
  - working: running;
  - Claude asks something: **waiting**, and the queue holds until I answer;
  - a finished-turn line: **done**; the final screen is saved to `results/task-<id>.txt` and the
    session stopped, so its memory is free for the next task (the conversation can be reopened
    with `claude --resume`);
  - a usage-limit message: **limited**, and the whole queue pauses until I resume it;
  - the session gone, or Claude never working within 5 minutes: **failed**.

## Checked

- Nine runner tests with real Claude screens, including a task finished between two checks, a
  question that holds the queue, a usage limit, and a frozen session left alone.
- End to end in a phone-sized browser against a test server with a fake `claude` (a script that
  prints real "working" then "done" screens, so no tokens): added on the Queue tab, started after
  about 4 s, done after about 16 s, result readable, nothing left running.

## Limits

- The usage-limit wording is not yet checked against a real limit screen.
- The budget counts every Claude session on the machine. With several open by hand, as during a
  work day, it says there is no room and the queue waits: by design, it is an overnight queue.
- Permission prompts stop a task until answered. Running tasks with fewer prompts (a permission
  mode per task) is a later choice.
