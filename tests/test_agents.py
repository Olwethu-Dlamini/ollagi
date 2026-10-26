import pytest

from ollagi import agents, config


def test_each_agent_starts_prompts_and_resumes_with_its_own_program():
    omp = agents.get("omp")
    assert omp.start() == ["omp"]
    assert omp.with_prompt("fix the tests") == ["omp", "fix the tests"]
    assert omp.resume("01a1772c") == ["omp", "--resume", "01a1772c"]
    assert agents.get("claude").resume("abc") == ["claude", "--resume", "abc"]


def test_an_unknown_agent_is_refused_with_the_choices():
    with pytest.raises(ValueError, match="claude, omp"):
        agents.get("codexx")


def test_claude_stays_the_default_so_existing_configs_behave_as_before():
    loaded = config.parse("")
    assert loaded.agent == "claude"
    assert loaded.agent_for("/anywhere").name == "claude"


def test_a_project_can_run_a_different_agent_than_the_default():
    loaded = config.parse(
        """
        agent = "omp"

        [[projects]]
        name = "simedia"
        directory = "/work/DATA!"
        agent = "claude"

        [[projects]]
        name = "ollagi"
        directory = "/work/ollagi"
        """
    )
    assert loaded.agent_for("/work/DATA!").name == "claude"
    assert loaded.agent_for("/work/DATA!/").name == "claude"  # the same folder written with a slash
    assert loaded.agent_for("/work/ollagi").name == "omp"     # no choice of its own: the default
    assert loaded.agent_for("/elsewhere").name == "omp"


def test_a_typo_in_the_config_is_refused_when_the_file_is_read():
    with pytest.raises(ValueError, match="unknown agent 'opm'"):
        config.parse('agent = "opm"')
    with pytest.raises(ValueError, match="unknown agent"):
        config.parse('[[projects]]\nname = "x"\ndirectory = "/x"\nagent = "gpt"')
