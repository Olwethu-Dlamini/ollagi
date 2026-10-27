# 0039: A dialog from another omp extension reads as needs_you

Date: 2026-10-27

## Context

The g6-close-out session read "working" on the page for over six hours while it waited for one answer:
the agent kit's guard hook asked "Guard: confirm command" (a `kubectl port-forward` to read last night's
logs) through `ctx.ui.confirm`. The state hook (0036) sees omp's ask tool and tool approvals, but a hook's
own dialog raises no event, so nothing told the page or the phone. To the user, ollagi looked slow.

omp gives every hook and extension in one process a shared event bus (`pi.events`). Checked with two
throwaway hooks loaded by `omp -p --hook`: one emitted at session start, the other received it.

## Decision

- The state hook listens on the bus: `ui:waiting` `{question, options}` writes needs_you with that
  question and choices; `ui:answered` writes working. The contract is in the hook's header.
- The agent kit's guard (`~/omp-by-oll/adapters/omp/hooks/pre/guard.ts`) emits `ui:waiting` just before its
  confirmation and `ui:answered` in a `finally` once it closes, so a failed dialog cannot leave a session
  reading needs_you. The guard knows nothing about ollagi; any extension can announce a dialog the same way.

## Consequences

- The page and the notifications show a guard confirmation as needs_you with Yes / No, like a question.
- Answering stays in the live terminal (Up/Down, Enter): the notification buttons for omp stay off (0036).
- A running omp keeps the hooks it loaded at start: sessions started before this change still hide such
  dialogs until they are restarted.
- Undo: remove the two `pi.events?.on` listeners here and the two `emit` calls in the guard.

## Checked

- `test_a_dialog_from_another_extension_reads_as_needs_you_until_answered` runs the real hook file in node
  with a stand-in for omp's API and bus: it failed before the listeners (the file said working).
- Live on archnox: an omp session started through ollagi was asked to `rm -rf` a folder that does not
  exist. Within 2 s the page showed needs_you "Guard: allow rm -rf /home/olwethu/ollagi-guard-probe-
  does-not-exist?" with Yes / No; answering No in the terminal gave "denied by user", then done.
- Found alongside: no phone was subscribed to notifications (`push.db` had 0 subscriptions), so no
  notification could have reached it in any case. Turning them on is System > Notifications on the phone.
