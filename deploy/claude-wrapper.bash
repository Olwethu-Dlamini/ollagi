# Make `claude`, typed in an interactive terminal, start through ollagi (docs/decisions/0015).
# The session then also shows on the ollagi page and the phone; it looks the same in the terminal.
# Load it from ~/.bashrc with:
#   [[ -r /media/oll/Linux/Projects/ollagi/deploy/claude-wrapper.bash ]] && source /media/oll/Linux/Projects/ollagi/deploy/claude-wrapper.bash
# Skip it once with `command claude ...` or `OLLAGI_OFF=1 claude ...`.

claude() {
  # Subcommands of `claude --help` (2.1.280): these are not chat sessions, so they go straight through.
  local subcommands=" agents attach auth auto-mode doctor gateway import install logs mcp plugin plugins project respawn rm setup-token stop kill ultrareview update upgrade remote-control "

  # Straight to the real claude when this is not a person at a terminal, when we are already in
  # tmux (an ollagi session, say), when ollagi is switched off or not installed.
  if [[ ! -t 0 || ! -t 1 || -n "$TMUX" || -n "$OLLAGI_OFF" ]] || ! command -v ollagi >/dev/null; then
    command claude "$@"; return
  fi
  # ...and for anything that is not an interactive chat: print mode, help, version.
  local arg
  for arg in "$@"; do
    case "$arg" in -p|--print|-h|--help|-v|--version|--output-format|--output-format=*) command claude "$@"; return ;; esac
  done
  if [[ $# -gt 0 && "$1" != -* && "$subcommands" == *" $1 "* ]]; then
    command claude "$@"; return
  fi

  ollagi here -- "$@"
}
