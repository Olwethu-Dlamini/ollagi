# 0040: Group tickets by the code they touch, not by how their titles read

Date: 2026-10-27. Replaces the rules of 0013.

## Context

0013 grouped tickets by title wording, labels and epics. Shown as a drawing on 2026-10-27, it was judged
wrong by its user: "I thought you grouped them by: these are revenue tickets, they work on the same codebase".
Two failures on the real tickets made the point: a frontend ticket and the backend ticket behind the same
feature had nothing in common in their titles and stayed apart, while test tickets for different pages read
alike and could be joined.

The working rule is the user's (and the product owner's decision 317 from the September Jira consolidation):
a group is worked in one session with one plan, but every ticket is delivered on its own branch, with its
own pull request and its own receipt.

## Decision

- `src/ollagi/code_areas.py` finds the areas of the code each ticket touches:
  - **code**: the files its Bitbucket pull requests change. A pull request belongs to every ticket key in its
    branch name or title ("T-7113-7119" names two). Bitbucket is asked only for my pull requests that name
    an open ticket's number, and the file lists are read side by side.
  - **page**: without a pull request, the areas whose words its title uses or whose epic it sits under, from
    a private map, `~/.config/ollagi/areas.toml`. ollagi is public, so no product or repository names are in
    the code. A changed file outside the map counts as "<repository>:<first three folders>".
  - Changelogs, version and lock files, translations and test-only files never count.
- `src/ollagi/grouping.py` gives each ticket ONE main area and groups tickets with the same main area. Most
  specific first: a specific area beats a broad one (marked `broad = true`: tests, a shared widget; and any
  folder the map does not know), then pull-request files beat title words, then the area with the most pull
  requests, then the area listed first in the map. The other areas show as "also touches".
- The page draws each group as a tree: the area at the root, one branch per ticket, solid when its pull
  requests prove the area and dashed when only the map does, with the evidence beside each ticket. A
  "How these groups were made" card explains the steps; lone tickets say why they are alone.
- A queued group's prompt says to deliver each ticket on its own branch, pull request and receipt.

## Consequences

- On my 25 open tickets (2026-10-27): 6 groups (Calendar 5, Marketing 4, four pairs) and 8 tickets alone.
  The frontend/backend pair now groups by its pull requests.
- The first load reads Bitbucket (about 20 s); tickets and evidence are then cached for 5 minutes like Jira.
  Without `~/.bitbucket.env`, or when Bitbucket fails, the map alone is used.
- The map needs care: an area's words decide tickets without pull requests. Editing the file shows on the
  next load.
- Undo: restore 0013's `grouping.py` and its tests from git; the drawing and card would need the old shape.

## Checked

- Tests (invented data): alike titles in different areas stay apart; files a pull request changes join
  tickets whose titles share nothing; a pull request decides over the title; a broad area shows as "also"
  and never chains groups; translation, changelog and test files are ignored; one branch names two tickets.
- Found live and fixed before this record: following every shared area (union-find, as 0013 did) joined 22
  of 25 tickets through tests and CI into one group. One main area per ticket replaced it; a test pins it.
  Listing all my pull requests took 22 s for 200; asking only for open tickets' numbers took 2 s.
- Live on a phone-sized screen: 6 trees, 11 solid and 6 dashed branches, the evidence and "also" lines
  readable, no script errors.
