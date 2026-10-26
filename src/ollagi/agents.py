"""The coding agents a session can run (docs/decisions/0035).

ollagi started as a control room for Claude Code only. Each agent here is described by the few things
ollagi needs from it:

- `name`: how it is chosen in the config and on the page, what a session's record stores as its
  "program", and the process name the kernel shows for it in /proc/<pid>/stat (`claude`, `omp`), which
  is how processes.py finds a session's process tree;
- `command`: the program started in the tmux window;
- how a first message is passed (both take it as the first argument: `claude "fix the tests"`,
  `omp "fix the tests"`), and how an earlier conversation is resumed (`--resume ID` for both).

Adding another agent (Codex, Gemini) means one more entry, plus a way to read its state (see
claude_screen.py and omp_state.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Agent:
    name: str
    command: tuple[str, ...]
    resume_flag: str = "--resume"

    def start(self) -> list[str]:
        """The command line for a fresh interactive session."""
        return list(self.command)

    def with_prompt(self, prompt: str) -> list[str]:
        """An interactive session that starts by working on `prompt` (the overnight queue uses this)."""
        return [*self.command, prompt]

    def resume(self, conversation_id: str) -> list[str]:
        """An interactive session that continues an earlier conversation."""
        return [*self.command, self.resume_flag, conversation_id]


AGENTS: dict[str, Agent] = {
    "claude": Agent("claude", ("claude",)),
    "omp": Agent("omp", ("omp",)),
}

NAMES = frozenset(AGENTS)
DEFAULT = "claude"


def get(name: str) -> Agent:
    try:
        return AGENTS[name]
    except KeyError:
        raise ValueError(f"unknown agent {name!r}: choose one of {', '.join(sorted(NAMES))}") from None
