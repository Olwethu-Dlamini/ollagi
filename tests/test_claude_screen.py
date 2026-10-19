"""The detector against real Claude Code screens (captured by Collie, MIT licence, see fixtures/collie)."""

from pathlib import Path

import pytest

from ollagi.claude_screen import plain, read

FIXTURES = Path(__file__).parent / "fixtures" / "collie"


def screen(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


@pytest.mark.parametrize(
    "name, state",
    [
        ("claude--v2301-idle", "idle"),
        ("claude--fresh-idle", "idle"),
        ("claude-lab--idle-after-turn--w82", "done"),
        ("claude--done", "done"),
        ("claude--working", "working"),
        ("claude--working-esc-to-interrupt", "working"),
        ("claude--v2301-working-quiet--w100", "working"),
        ("claude--permission-bash", "needs_you"),
        ("claude--permission-edit", "needs_you"),
        ("claude--plan-approval", "needs_you"),
        ("claude--select-menu", "needs_you"),
        ("claude--trust-prompt", "needs_you"),
    ],
)
def test_each_real_screen_gets_its_state(name, state):
    assert read(screen(name)).state == state


def test_a_bash_permission_gives_its_question_and_three_choices():
    reading = read(screen("claude--permission-bash"))
    assert reading.question == "Do you want to proceed?"
    assert [o.label for o in reading.options] == [
        "Yes",
        "Yes, and don’t ask again for: mkfifo fixture-fifo *",
        "No",
    ]


def test_a_question_menu_keeps_options_after_a_rule_and_skips_descriptions():
    reading = read(screen("claude--select-menu"))
    assert reading.question == "Which color theme should the dashboard use?"
    assert [o.label for o in reading.options] == ["Red", "Green", "Blue", "Type something.", "Chat about this"]


def test_plan_approval_has_four_choices():
    reading = read(screen("claude--plan-approval"))
    assert [o.number for o in reading.options] == [1, 2, 3, 4]
    assert reading.question.startswith("Claude has written up a plan")


def test_the_feedback_survey_while_working_is_not_mistaken_for_a_menu():
    # "1: Bad  2: Fine  3: Good" uses colons, and Claude is still working underneath.
    assert "1: Bad" in plain(screen("claude--working"))
    assert read(screen("claude--working")).state == "working"


def test_a_numbered_list_in_an_answer_is_not_a_menu():
    text = "● Steps:\n  1. Read the file\n────\n❯ \n────\n"
    assert read(text).state == "idle"


def test_unrecognised_screens_are_unknown():
    assert read("oll@omarchy ~ $ ls\nfile.txt\n").state == "unknown"


def test_colour_codes_are_removed_before_matching():
    assert plain("\x1b[38;2;215;119;87m✢\x1b[0m Puzzling… (3s)") == "✢ Puzzling… (3s)"


def test_a_finished_answer_with_a_numbered_list_is_done_not_a_menu():
    text = (
        "● Here is the plan:\n  1. Read the config\n  2. Add the watcher\n  3. Write the tests\n"
        "✻ Brewed for 12s\n────\n❯ \n────\n"
    )
    assert read(text).state == "done"
