# 0013: Group similar Jira tickets with rules that can be read and checked

Date: 2026-10-19

## Context

Related tickets are cheaper and better done in one Claude session: it reads the shared code once.
ollagi reads my open tickets with the Jira token already on this machine (`~/.jira.env`), read only:
the SiMedia rule is that tooling never changes a ticket's status, so there is no write call.

## Decision

Two tickets are linked by the first rule that fits, and every link records why:

1. same title start (the part before a colon, else the first two words);
2. a shared specific label (on at most 20% of the tickets);
3. the same small parent (at most 6 of the tickets under it);
4. titles sharing at least half their words;
5. any shared label or parent, plus titles sharing at least a quarter of their words.

Rules 4 and 5 never link titles with different colon prefixes. Links are followed into groups
(union-find). A group's reason lists what all its tickets share, or, for a chain, its links.

Similarity is the Jaccard measure over title words after dropping common words and numbers. No
machine learning: every grouping can be explained by pointing at the rule.

## How the rules were found (counts only; ticket data never goes in this public repo)

On my 58 open tickets (2026-10-19), the first version (rules 4 and 5 only) made 1 group of 22 that
mixed two kinds of test tickets, and missed groups that were obvious by eye (a review label on 5
tickets, small epics, same-prefix titles). The rules above give 10 groups covering 49 tickets.
Three bugs found on the way, each now pinned by a test: a label on 2 of 3 tickets counted as "too
common"; the plural rule turned "process" into "proce"; a 2-letter prefix ("QA:") was not seen as
a prefix, because words under 3 letters are ignored for similarity.

## Limits

A group can be too big for one session (18 here). The page lets me pick which of its tickets to
queue together.
