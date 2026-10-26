# 0037: Resume an earlier omp conversation from the page

Date: 2026-10-26

## Context

The New sheet offers a folder's recent Claude conversations to resume (0033). A folder that runs omp
(0035) offered nothing, and a Claude conversation id handed to `omp --resume` would resume nothing.

## Decision

- `src/ollagi/omp_conversations.py` lists a folder's omp conversations, newest first, from omp's own
  files (`~/.omp/agent/sessions/*/<time>_<id>.jsonl`). A file belongs to the folder when the `cwd` it
  records is that folder; omp's way of naming its sub-folders is not copied. Only the first lines are
  read: the title (when omp has given one) and the session line with the id and folder.
- The list and the server's check follow the folder's agent: an omp folder offers omp conversations and
  resumes with `omp --resume ID`; a Claude folder works as before. The server still accepts only an id
  from that same list, so a Claude id never reaches omp, and the other way round.
- A conversation a running omp session has open is left out: two omp processes writing one file would
  corrupt it. The state hook (0036) records the open conversation's id, read back by
  `omp_state.open_conversations()`.

## Consequences

- Resume from the phone works for both agents.
- An omp started in a plain terminal, outside ollagi, has no state file, so its conversation is not left
  out. Start omp through ollagi (`ollagi here`) to be covered.
- Undo: `resumable()` back to Claude-only and remove `omp_conversations.py`.

## Checked

2026-10-26: a real `omp -p` run in a throwaway folder: the hook recorded conversation
01a178bb-ffe3-727d-8da2-8d4a0827e2cf, the session file was `..._01a178bb-....jsonl`, and
`omp_conversations.recent()` listed it for that folder (untitled: print mode gives no title).
Tests: 4 in `tests/test_omp_conversations.py` over files shaped like omp's, 2 page tests; the
leave-out test fails when running sessions' conversations are not left out. Suite: 281 passed.
