# Make `claude` and `omp`, typed in an interactive terminal, start through ollagi (docs/decisions/0015,
# 0042). The session then also shows on the ollagi page and the phone, live; it looks the same in the
# terminal. Each command starts the agent that was typed, whatever the config's default agent is.
# Load it from ~/.bashrc with (the path of the checkout the service runs):
#   [[ -r ~/work/ollagi-agents-omp/deploy/agent-wrapper.bash ]] && source ~/work/ollagi-agents-omp/deploy/agent-wrapper.bash
# Skip it once with `command omp ...` or `OLLAGI_OFF=1 omp ...`.

# Runs agent $1 with the remaining arguments: through `ollagi here` for a person starting a chat at a
# terminal, straight to the real program for everything else. $2 lists the agent's subcommands (these are
# not chat sessions) and $3 its options that mean "not an interactive chat"; both space-padded.
_ollagi_agent() {
  local agent=$1 subcommands=$2 not_a_chat=$3
  shift 3

  # Straight to the real program when this is not a person at a terminal, when we are already in tmux
  # (an ollagi session, say), when ollagi is switched off or not installed.
  if [[ ! -t 0 || ! -t 1 || -n "$TMUX" || -n "$OLLAGI_OFF" ]] || ! command -v ollagi >/dev/null; then
    command "$agent" "$@"; return
  fi
  local arg
  for arg in "$@"; do
    if [[ "$not_a_chat" == *" ${arg%%=*} "* ]]; then
      command "$agent" "$@"; return
    fi
  done
  if [[ $# -gt 0 && "$1" != -* && "$subcommands" == *" $1 "* ]]; then
    command "$agent" "$@"; return
  fi

  ollagi here --agent "$agent" -- "$@"
}

claude() {
  # Subcommands of `claude --help` (2.1.280).
  _ollagi_agent claude \
    " agents attach auth auto-mode doctor gateway import install logs mcp plugin plugins project respawn rm setup-token stop kill ultrareview update upgrade remote-control " \
    " -p --print -h --help -v --version --output-format " \
    "$@"
}

omp() {
  # Subcommands of `omp --help` (18.16.0). --mode (json, rpc) is a program talking to omp; --export and
  # --alias do their job and exit.
  _ollagi_agent omp \
    " acp agents anonymize auth auth-broker auth-gateway bench browser-relay cleanse clip collab commit completions compress config dry-balance find gallery gc git grep grievances if-bench images install join login models play plugin predict ps read render say search session setup share shell skill ssh stats stream tiny-models token toks ttsr update usage worktree " \
    " -p --print -h --help -v --version --mode --export --alias " \
    "$@"
}
