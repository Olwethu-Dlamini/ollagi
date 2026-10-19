# 0014: Slack through an outbox: ollagi drafts, I approve every message

Date: 2026-10-19

## Context

My standing rule for Slack: nothing is posted in my name until I have seen the exact text and said
OK, for every single message; an OK never carries over to the next one. ollagi must follow the same
rule, and use the Slack helper already set up on this machine (`~/slack.sh`, which keeps the token
fresh and turns "@Name" into real mentions).

## Decision

- ollagi only makes **drafts** (`src/ollagi/slack_outbox.py`, a table in the same SQLite file).
- **Preview** runs `slack.sh preview` (sends nothing) to show who the message would notify.
- **Send** is a button on one draft. The page shows the exact text in a confirmation, and the
  server sends only if the text confirmed equals the stored text. A sent draft can never be sent
  again; a refused send stays a draft.
- Optional `[slack] drafts_to = "<channel>"` in the config: queue events (task done, waiting for
  you, usage limit, failed) become drafts there. Still drafts: they wait for my Send like any other.

## Checked

Seven outbox tests with a fake `slack.sh`; API tests; and a walk on the real page with the real
`slack.sh`: preview answered "notifies: nobody", the Send confirmation showed the exact text and
was dismissed, the draft stayed a draft and was discarded. Nothing was posted.
