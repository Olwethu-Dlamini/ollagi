"""Group similar tickets, so related work can be done in one Claude session (docs/decisions/0013).

Two tickets are linked when any of these holds (checked against my real ticket list, 2026-10-19):

  1. same title start: the part before a colon ("Calendar: ..."), or else the first two words
     ("Manage Offers ...");
  2. a shared *specific* label, one on at most 20% of the tickets (a review batch, say), not one
     on a third of everything;
  3. the same *small* parent epic, one with at most 6 of the tickets under it;
  4. their titles share at least half of their words (WORDS_ALONE);
  5. a shared label or parent of any size, and titles sharing at least a quarter (WORDS_WITH_LINK).

Rules 4 and 5 never link two titles with *different* colon prefixes: "Cypress: x failing" and
"K6: x failing" are worded alike but are different kinds of work.

"Share half their words" is the Jaccard similarity: words in both titles divided by words in either.
Common words ("the", "add", "fix"...) and numbers are left out first, because every title has them.
Links are then followed to whole groups (a "union-find": if A is like B and B is like C, all three
are one group). Each group says *why* it is a group, in words, so the result can be checked by eye.
"""

import re
from collections import Counter
from dataclasses import dataclass

from ollagi.jira import Ticket

WORDS_ALONE = 0.5
WORDS_WITH_LINK = 0.25
COMMON_LABEL_SHARE = 0.6  # a label on more than 60% of all tickets says nothing about similarity...
COMMON_LABEL_MIN_TICKETS = 10  # ...but "60% of 3 tickets" is just two tickets, so only judge from 10 up
SPECIFIC_LABEL_SHARE = 0.2  # a label on at most 20% of the tickets links on its own (rule 2)
SMALL_PARENT = 6  # a parent with at most this many of the tickets links on its own (rule 3)
STOPWORDS = set("""
a an and are as at be by for from has have in into is it its of on or that the this to was were will with
add adds added fix fixes fixed make makes use uses using new old not no when then than does do don't
""".split())


@dataclass(frozen=True)
class Group:
    tickets: list[Ticket]
    reason: str


def words_in_order(text: str) -> list[str]:
    found = [singular(w) for w in re.findall(r"[a-z][a-z0-9-]+", text.lower()) if len(w) >= 3]
    return [w for w in found if w not in STOPWORDS]


def words(title: str) -> set[str]:
    return set(words_in_order(title))


def lead(title: str) -> tuple[str, str]:
    """How a title starts: ("colon", "calendar") for "Calendar: ...", else ("start", first two words)."""
    head, colon, _ = title.partition(":")
    if colon and 0 < len(head.strip()) <= 40:
        # Read the prefix as written: "K6" is a real prefix even though it is too short to count
        # as a word for similarity.
        return "colon", " ".join(head.lower().split())
    first = words_in_order(title)[:2]
    return ("start", " ".join(first)) if len(first) == 2 else ("none", "")


def singular(word: str) -> str:
    """A rough plural rule: "tests" -> "test". Never "process" -> "proces" (ends in ss) or short words."""
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def group(tickets: list[Ticket]) -> list[Group]:
    """Groups of two or more similar tickets, biggest first. Tickets like no other are left out."""
    label_counts = Counter(label for t in tickets for label in t.labels)
    parent_counts = Counter(t.parent for t in tickets if t.parent)
    enough = len(tickets) >= COMMON_LABEL_MIN_TICKETS
    too_common = {label for label, n in label_counts.items() if enough and n > COMMON_LABEL_SHARE * len(tickets)}
    specific = {label for label, n in label_counts.items() if not enough or n <= SPECIFIC_LABEL_SHARE * len(tickets)}
    title_words = {t.key: words(t.summary) for t in tickets}
    leads = {t.key: lead(t.summary) for t in tickets}

    def link_reason(a: Ticket, b: Ticket) -> str | None:
        """Why a and b belong together, in words, or None when they do not."""
        lead_a, lead_b = leads[a.key], leads[b.key]
        if lead_a[0] != "none" and lead_a == lead_b:
            return f"same start {lead_a[1]}"  # rule 1
        shared_labels = set(a.labels) & set(b.labels)
        if shared_labels & specific:
            return "same label " + ", ".join(sorted(shared_labels & specific))  # rule 2
        same_parent = a.parent is not None and a.parent == b.parent
        if same_parent and parent_counts[a.parent] <= SMALL_PARENT:
            return f"same parent {a.parent}"  # rule 3
        if lead_a[0] == lead_b[0] == "colon":
            return None  # different colon prefixes: different kinds of work, however alike the words
        similarity = jaccard(title_words[a.key], title_words[b.key])
        shares = bool(shared_labels - too_common) or same_parent
        if similarity >= WORDS_ALONE or (shares and similarity >= WORDS_WITH_LINK):
            return f"similar titles ({similarity:.0%} of words shared)"  # rules 4 and 5
        return None

    # Union-find: every ticket starts as its own group; each link merges two groups.
    leader = {t.key: t.key for t in tickets}

    def find(key: str) -> str:
        while leader[key] != key:
            leader[key] = leader[leader[key]]  # shorten the path as we go
            key = leader[key]
        return key

    links = []  # (a, b, reason) for every link that joined two different groups
    for i, a in enumerate(tickets):
        for b in tickets[i + 1:]:
            reason = link_reason(a, b)
            if reason and find(a.key) != find(b.key):
                leader[find(a.key)] = find(b.key)
                links.append((a.key, b.key, reason))

    members: dict[str, list[Ticket]] = {}
    for t in tickets:
        members.setdefault(find(t.key), []).append(t)
    groups = []
    for ts in members.values():
        if len(ts) > 1:
            keys = {t.key for t in ts}
            own_links = [(a, b, r) for a, b, r in links if a in keys]
            groups.append(Group(ts, explain(ts, title_words, leads, own_links)))
    return sorted(groups, key=lambda g: -len(g.tickets))


def explain(tickets: list[Ticket], title_words: dict[str, set[str]], leads: dict[str, tuple[str, str]],
            links: list[tuple[str, str, str]]) -> str:
    """What all the tickets share; for a chain where nothing is shared by all, the links themselves."""
    parts = []
    starts = {leads[t.key] for t in tickets}
    if len(starts) == 1 and next(iter(starts))[0] != "none":
        parts.append("same start: " + next(iter(starts))[1])
    common_words = set.intersection(*(title_words[t.key] for t in tickets))
    if common_words:
        parts.append("all titles mention: " + ", ".join(sorted(common_words)))
    common_labels = set.intersection(*(set(t.labels) for t in tickets))
    if common_labels:
        parts.append("same label: " + ", ".join(sorted(common_labels)))
    parents = {t.parent for t in tickets}
    if len(parents) == 1 and None not in parents:
        parts.append(f"same parent: {parents.pop()}")
    if parts:
        return " · ".join(parts)
    shown = [f"{a} + {b}: {reason}" for a, b, reason in links[:4]]
    more = f" (and {len(links) - 4} more links)" if len(links) > 4 else ""
    return "; ".join(shown) + more


def prompt_for(tickets: list[Ticket]) -> str:
    """The task prompt for working on a group in one session."""
    lines = [f"- {t.key}: {t.summary} ({t.status}) {t.url}" for t in tickets]
    return (
        "These Jira tickets are related and are to be worked on together in this session:\n"
        + "\n".join(lines)
        + "\n\nStart by reading each ticket and saying what they have in common and the order you "
        "would take them in, then wait for my go-ahead before changing anything."
    )
