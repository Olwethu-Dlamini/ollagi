"""Grouping, tested on invented tickets. Never put real ticket data here: this repo is public."""

from ollagi.grouping import group, jaccard, prompt_for, words
from ollagi.jira import Ticket, parse_issue, read_env


def ticket(key, summary, labels=(), parent=None, status="To Do"):
    return Ticket(key, summary, status, tuple(labels), parent, "Task", f"https://jira.example/browse/{key}")


def test_title_words_drop_common_words_numbers_and_plurals():
    assert words("Fix the 3 failing tests in the Login page") == {"failing", "test", "login", "page"}


def test_plurals_lose_one_s_but_words_ending_in_ss_keep_theirs():
    assert words("tests processes access class") == {"test", "processe", "access", "class"}


def test_jaccard_is_shared_over_all():
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3


def test_same_pattern_titles_form_one_group():
    tickets = [
        ticket("T-1", "E2E: checkout - 3 test(s) failing"),
        ticket("T-2", "E2E: settings - 9 test(s) failing"),
        ticket("T-3", "E2E: search - 1 test(s) failing"),
        ticket("T-4", "Export the yearly report as CSV"),
    ]
    [g] = group(tickets)
    assert [t.key for t in g.tickets] == ["T-1", "T-2", "T-3"]
    assert "all titles mention: e2e, failing, test" in g.reason


def test_a_shared_label_links_titles_that_are_only_a_little_alike():
    a = ticket("T-1", "Login page loses the session cookie", labels=["security"])
    b = ticket("T-2", "Session cookie missing the secure flag", labels=["security"])
    c = ticket("T-3", "Session timeout too short on the dashboard")
    groups = group([a, b, c])
    assert [[t.key for t in g.tickets] for g in groups] == [["T-1", "T-2"]]
    assert "same label: security" in groups[0].reason


def test_a_label_on_almost_every_ticket_says_nothing():
    common = ["team-x"]
    tickets = [ticket("T-1", "Login page cookie", common), ticket("T-2", "Cookie banner text", common)]
    others = ["Yearly report export", "Dark mode toggle", "Printer driver", "Invoice rounding",
              "Calendar holidays", "Weather widget", "Currency symbols", "Password reset mail"]
    tickets += [ticket(f"T-{n}", title, common) for n, title in enumerate(others, start=3)]
    # "cookie" is 1 of 5 words (0.2) between T-1 and T-2, and team-x is on all 10 tickets, so no link.
    assert group(tickets) == []


def test_a_shared_parent_counts_like_a_label():
    a = ticket("T-1", "Budget wizard shows the wrong month", parent="EPIC-1")
    b = ticket("T-2", "Budget wizard month picker skips March", parent="EPIC-1")
    [g] = group([a, b])
    assert "same parent: EPIC-1" in g.reason


def test_unrelated_tickets_are_not_grouped():
    assert group([ticket("T-1", "Export report as CSV"), ticket("T-2", "Dark mode for settings")]) == []


def test_the_prompt_lists_every_ticket_and_asks_before_changing_anything():
    text = prompt_for([ticket("T-1", "One"), ticket("T-2", "Two")])
    assert "- T-1: One (To Do) https://jira.example/browse/T-1" in text
    assert "wait for my go-ahead" in text


def test_jira_env_files_allow_export_and_quotes():
    env = read_env('export JIRA_SITE="example.atlassian.net"\n# a comment\nJIRA_EMAIL=me@example.com\n')
    assert env == {"JIRA_SITE": "example.atlassian.net", "JIRA_EMAIL": "me@example.com"}


def test_an_issue_from_the_search_api_becomes_a_ticket():
    issue = {"key": "T-9", "fields": {"summary": "S", "status": {"name": "To Do"}, "labels": ["x"],
                                      "parent": {"key": "EPIC-2"}, "issuetype": {"name": "Bug"}}}
    t = parse_issue(issue, "example.atlassian.net")
    assert (t.key, t.parent, t.labels, t.url) == ("T-9", "EPIC-2", ("x",), "https://example.atlassian.net/browse/T-9")


# ---- the refined rules (decision 0013) -------------------------------------------------------

def test_the_same_title_start_links_tickets_with_different_wording():
    a = ticket("T-1", "Calendar: show where an event takes place")
    b = ticket("T-2", "Calendar: event names appear in the wrong language")
    [g] = group([a, b])
    assert "same start: calendar" in g.reason


def test_titles_without_a_colon_compare_their_first_two_words():
    a = ticket("T-1", "Manage Offers images tab loads nothing")
    b = ticket("T-2", "Manage Offers captions tab is empty")
    c = ticket("T-3", "Manage users page is slow")
    groups = group([a, b, c])
    assert [[t.key for t in g.tickets] for g in groups] == [["T-1", "T-2"]]


def test_different_colon_prefixes_keep_similar_titles_apart():
    a = ticket("T-1", "E2E: checkout - 3 test(s) failing")
    b = ticket("T-2", "E2E: settings - 9 test(s) failing")
    c = ticket("T-3", "LOAD: checkout - 2 test(s) failing")
    groups = group([a, b, c])
    assert [[t.key for t in g.tickets] for g in groups] == [["T-1", "T-2"]]


def test_a_specific_label_links_on_its_own():
    review = ["review-batch-7"]
    tickets = [ticket("T-1", "Refresh token left in local storage", review),
               ticket("T-2", "No attempt limit on the code check", review)]
    tickets += [ticket(f"T-{n}", title) for n, title in enumerate(
        ["Yearly report export", "Dark mode toggle", "Printer driver", "Invoice rounding",
         "Calendar holidays", "Weather widget", "Currency symbols", "Password reset mail", "Fonts"], start=3)]
    [g] = group(tickets)  # review-batch-7 is on 2 of 11 tickets: specific
    assert [t.key for t in g.tickets] == ["T-1", "T-2"]
    assert "same label: review-batch-7" in g.reason


def test_a_small_parent_links_on_its_own_but_a_big_one_does_not():
    small = [ticket("S-1", "Show the event venue", parent="EPIC-S"),
             ticket("S-2", "Last month preset in the date filter", parent="EPIC-S")]
    big = [ticket(f"B-{n}", title, parent="EPIC-B") for n, title in enumerate(
        ["Printer driver", "Invoice rounding", "Weather widget", "Currency symbols",
         "Password reset mail", "Fonts", "Yearly export"], start=1)]
    groups = group(small + big)  # EPIC-B has 7 tickets: too big to mean "related"
    assert [[t.key for t in g.tickets] for g in groups] == [["S-1", "S-2"]]
    assert "same parent: EPIC-S" in groups[0].reason


def test_a_two_letter_prefix_still_counts_as_a_colon_prefix():
    # Words under 3 letters are ignored for similarity, but a prefix like "QA:" is still a prefix.
    a = ticket("T-1", "E2E: checkout - 3 test(s) failing", parent="EPIC-BIG")
    b = ticket("T-2", "QA: checkout - 2 test check(s) failing", parent="EPIC-BIG")
    filler = [ticket(f"F-{n}", f"Filler title {w}", parent="EPIC-BIG")
              for n, w in enumerate(["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"])]
    together = [g for g in group([a, b, *filler]) if {"T-1", "T-2"} <= {t.key for t in g.tickets}]
    assert together == []


def test_a_chained_group_explains_its_links():
    # A and B share a specific label, B and C a small parent: nothing is common to all three.
    a = ticket("T-1", "Refresh token left behind", labels=["review-7"])
    b = ticket("T-2", "Code check has no attempt limit", labels=["review-7"], parent="EPIC-S")
    c = ticket("T-3", "Signing key cannot rotate", parent="EPIC-S")
    [g] = group([a, b, c])
    assert "T-1 + T-2: same label review-7" in g.reason
    assert "T-2 + T-3: same parent EPIC-S" in g.reason
