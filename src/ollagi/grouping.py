"""Group tickets by the code they work on, so one session works them together (docs/decisions/0040).

src/ollagi/code_areas.py says which areas of the code each ticket touches, from its pull requests or the
private area map. Each ticket then gets ONE main area, and a group is the tickets sharing a main area:
all the Calendar tickets, all the Marketing tickets.

The main area is the most specific one with the strongest evidence:
  1. a specific area beats a broad one (tests, CI, a shared widget, a folder the map does not know);
  2. then the files a pull request changes beat the words of a title;
  3. then the area with the most pull requests, or, between map areas, the one listed first in the map.
The other areas a ticket touches are shown as "also touches"; they never merge groups. (Following every
shared area, as a first version did, chained 22 of 25 real tickets into one group through tests and CI.)

Title wording alone is not evidence: "Cypress: checkout failing" and "Cypress: search failing" read alike
and live in different code. Decision 0013's title rules were replaced by this one (0040).

The group is worked in one session, but each ticket is delivered on its own: its own branch, pull request
and receipt (the user's rule, 2026-10-27).
"""

from dataclasses import dataclass, field

from ollagi.code_areas import Evidence
from ollagi.jira import Ticket

KINDS = [
    {"id": "code", "name": "from pull requests",
     "text": "The ticket's pull requests change files in this area. The strongest evidence."},
    {"id": "page", "name": "from the area map",
     "text": "No pull request names it there yet: its title uses the area's words, or it sits under the area's epic."},
]


@dataclass(frozen=True)
class Group:
    area: str
    tickets: list[Ticket]
    reason: str
    main: dict[str, Evidence] = field(default_factory=dict)  # ticket key -> why it is in this area


def main_area(ticket: Ticket, evidence: dict[str, list[Evidence]]) -> Evidence | None:
    found = evidence.get(ticket.key, ())
    # evidence_for lists code areas busiest first, then the map's; sorted() keeps that order on ties.
    return min(found, key=lambda e: (e.broad, e.kind != "code"), default=None)


def also_touches(ticket: Ticket, evidence: dict[str, list[Evidence]]) -> list[Evidence]:
    """The ticket's other areas. Folders the map does not know are shown once per repository."""
    main = main_area(ticket, evidence)
    if not main:
        return []
    seen, found = {main.area}, []
    for e in evidence.get(ticket.key, ()):
        name = e.area.split(":")[0] if e.broad and ":" in e.area else e.area
        if name not in seen:
            seen.add(name)
            found.append(Evidence(name, e.kind, e.detail, e.broad))
    return found


def group(tickets: list[Ticket], evidence: dict[str, list[Evidence]]) -> list[Group]:
    """Groups of two or more tickets with the same main area, biggest first."""
    by_area: dict[str, list[tuple[Ticket, Evidence]]] = {}
    for t in tickets:
        main = main_area(t, evidence)
        if main:
            by_area.setdefault(main.area, []).append((t, main))
    groups = []
    for area, members in by_area.items():
        if len(members) > 1:
            from_code = sum(e.kind == "code" for _, e in members)
            reason = f"{len(members)} tickets in {area}: {from_code} by their pull requests, {len(members) - from_code} by the area map"
            groups.append(Group(area, [t for t, _ in members], reason, {t.key: e for t, e in members}))
    return sorted(groups, key=lambda g: (-len(g.tickets), g.area))


def why_alone(ticket: Ticket, evidence: dict[str, list[Evidence]]) -> str:
    main = main_area(ticket, evidence)
    if not main:
        return "no area found: no pull request yet, and its title names no area in the map"
    return f"the only open ticket in {main.area} ({main.detail})"


def prompt_for(tickets: list[Ticket]) -> str:
    """The task prompt for working on a group in one session."""
    lines = [f"- {t.key}: {t.summary} ({t.status}) {t.url}" for t in tickets]
    return (
        "These Jira tickets touch the same code and are to be worked on together in this session:\n"
        + "\n".join(lines)
        + "\n\nStart by reading each ticket and saying what code they share and the order you would take them "
        "in, then wait for my go-ahead before changing anything. Deliver each ticket on its own: its own "
        "branch, pull request and receipt; a pull request never carries another ticket's change."
    )
