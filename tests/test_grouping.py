"""Grouping by shared code, tested on invented tickets and invented code. Never put real data here: this
repo is public."""

from ollagi.code_areas import Area, evidence_for, keys_in, load_areas, path_area
from ollagi.grouping import KINDS, also_touches, group, prompt_for, why_alone
from ollagi.jira import Ticket, parse_issue, read_env


def ticket(key, summary, labels=(), parent=None, status="To Do"):
    return Ticket(key, summary, status, tuple(labels), parent, "Task", f"https://jira.example/browse/{key}")


AREAS = [
    Area("Calendar", words=("calendar",), epics=("EPIC-C",), code=("web:src/pages/Calendar", "events-api")),
    Area("Checkout", words=("checkout",), code=("web:src/pages/Checkout",)),
    Area("Search", words=("search",), code=("web:src/pages/Search",)),
]


class FakeCode:
    """Pull requests and the files each changes, invented."""

    def __init__(self, files_by_pr):
        self.files = files_by_pr  # {(id, repo, branch): [paths]}

    def my_pull_requests(self, keys):
        return [{"id": i, "repo": repo, "branch": branch, "title": "", "updated": "x"} for i, repo, branch in self.files]

    def changed_paths(self, pr):
        return self.files[(pr["id"], pr["repo"], pr["branch"])]


def keys(groups):
    return [[t.key for t in g.tickets] for g in groups]


def test_titles_naming_the_same_area_group_whatever_their_wording():
    a = ticket("T-1", "Calendar: the arrow overlaps the header")
    b = ticket("T-2", "Month arrows switch the picker to custom", parent="EPIC-C")  # the epic says where it lives
    c = ticket("T-3", "Export the yearly report")
    [g] = group([a, b, c], evidence_for([a, b, c], AREAS))
    assert (g.area, keys([g])) == ("Calendar", [["T-1", "T-2"]])
    assert (g.main["T-1"].detail, g.main["T-2"].detail) == ('title says "calendar"', "epic EPIC-C")


def test_alike_titles_in_different_areas_stay_apart():
    # The title rules (0013) put these together; they are different pages and different code.
    a = ticket("T-1", "Cypress: checkout - 3 test(s) failing")
    b = ticket("T-2", "Cypress: search - 1 test(s) failing")
    assert group([a, b], evidence_for([a, b], AREAS)) == []


def test_a_broad_area_is_shown_but_never_chains_groups_together():
    # Found live 2026-10-27: following every shared area joined 22 of 25 tickets through tests and CI.
    areas = AREAS + [Area("Tests", words=("cypress",), broad=True)]
    a = ticket("T-1", "Cypress: checkout - 3 test(s) failing")
    b = ticket("T-2", "Checkout total rounds wrongly")
    c = ticket("T-3", "Cypress: search - 1 test(s) failing")
    evidence = evidence_for([a, b, c], areas)
    [g] = group([a, b, c], evidence)
    assert (g.area, keys([g])) == ("Checkout", [["T-1", "T-2"]])
    assert [e.area for e in also_touches(a, evidence)] == ["Tests"]
    assert why_alone(c, evidence) == 'the only open ticket in Search (title says "search")'


def test_files_a_pull_request_changes_put_tickets_together_whose_titles_share_nothing():
    a = ticket("T-1", "Captions never listed in view mode")
    b = ticket("T-2", "Delete returns 404 from the routes")
    c = ticket("T-3", "Bump the build")
    code = FakeCode({
        (11, "web", "fix/T-1-captions"): ["src/pages/Offers/Captions.tsx", "CHANGELOG.md", "package.json"],
        (12, "web", "fix/T-2-routes"): ["src/pages/Offers/api.ts"],
        (13, "web", "fix/T-3-bump"): ["CHANGELOG.md", "package.json", "cypress/e2e/offers.cy.ts"],  # nothing real
    })
    evidence = evidence_for([a, b, c], AREAS, code)
    [g] = group([a, b, c], evidence)
    assert (g.area, keys([g])) == ("web:src/pages/Offers", [["T-1", "T-2"]])
    assert (g.main["T-1"].kind, g.main["T-1"].detail, g.main["T-2"].detail) == ("code", "PR #11", "PR #12")
    assert why_alone(c, evidence).startswith("no area found")


def test_a_pull_request_decides_the_area_over_the_title():
    a = ticket("T-1", "Calendar arrow overlaps the checkout header")  # names two areas
    b = ticket("T-2", "Checkout total rounds wrongly")
    code = FakeCode({(21, "web", "fix/T-1-arrow"): ["src/pages/Checkout/header.scss"]})
    evidence = evidence_for([a, b], AREAS, code)
    [g] = group([a, b], evidence)
    assert (g.area, g.main["T-1"].kind, g.main["T-1"].detail) == ("Checkout", "code", "PR #21")
    assert [e.area for e in also_touches(a, evidence)] == ["Calendar"]


def test_one_branch_can_name_two_tickets():
    assert keys_in("fix/T-7113-7119-cypress-specs") == {"T-7113", "T-7119"}
    assert keys_in("feature/T-7087-phone-2") == {"T-7087"}


def test_a_changed_file_maps_to_its_area_else_to_its_folder():
    assert path_area("web", "src/pages/Calendar/calendar.scss", AREAS) == "Calendar"
    assert path_area("events-api", "Controllers/EventsController.cs", AREAS) == "Calendar"
    assert path_area("web", "src/pages/CalendarOld/x.ts", AREAS) == "web:src/pages/CalendarOld"  # a prefix is a folder
    assert path_area("web", "CHANGELOG.md", AREAS) is None
    assert path_area("web", "src/locales/de/translation.json", AREAS) is None  # every UI change touches these
    assert path_area("api", "Api.Tests/FooTests.cs", AREAS) is None


def test_the_area_map_is_read_from_toml(tmp_path):
    path = tmp_path / "areas.toml"
    path.write_text('[[area]]\nname = "Calendar"\nwords = ["Calendar"]\ncode = ["web:src/pages/Calendar"]\n')
    assert load_areas(path) == [Area("Calendar", ("calendar",), (), ("web:src/pages/Calendar",), False)]
    assert load_areas(tmp_path / "missing.toml") == []


def test_every_kind_of_evidence_is_explained():
    a, b = ticket("T-1", "Calendar: a"), ticket("T-2", "Calendar: b")
    [g] = group([a, b], evidence_for([a, b], AREAS))
    assert {k["id"] for k in KINDS} >= {e.kind for e in g.main.values()}


def test_the_prompt_lists_every_ticket_asks_first_and_keeps_one_pull_request_per_ticket():
    text = prompt_for([ticket("T-1", "One"), ticket("T-2", "Two")])
    assert "- T-1: One (To Do) https://jira.example/browse/T-1" in text
    assert "wait for my go-ahead" in text
    assert "its own branch, pull request and receipt" in text


def test_jira_env_files_allow_export_and_quotes():
    env = read_env('export JIRA_SITE="example.atlassian.net"\n# a comment\nJIRA_EMAIL=me@example.com\n')
    assert env == {"JIRA_SITE": "example.atlassian.net", "JIRA_EMAIL": "me@example.com"}


def test_an_issue_from_the_search_api_becomes_a_ticket():
    issue = {"key": "T-9", "fields": {"summary": "S", "status": {"name": "To Do"}, "labels": ["x"],
                                      "parent": {"key": "EPIC-2"}, "issuetype": {"name": "Bug"}}}
    t = parse_issue(issue, "example.atlassian.net")
    assert (t.key, t.parent, t.labels, t.url) == ("T-9", "EPIC-2", ("x",), "https://example.atlassian.net/browse/T-9")
