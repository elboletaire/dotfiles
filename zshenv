#
# Defines environment variables.
#
# Authors:
#   Sorin Ionescu <sorin.ionescu@gmail.com>
#

# herdr hands its panes its own agent link, which points at prezto's. Prezto's
# ssh module would then point its link back at herdr's -- a loop that breaks
# the agent for every shell until another one repairs it. Resolve the chain to
# the real socket first, so prezto only ever links to that.
if [[ -L "$SSH_AUTH_SOCK" && -S "${SSH_AUTH_SOCK:A}" ]]; then
  export SSH_AUTH_SOCK="${SSH_AUTH_SOCK:A}"
fi

# Ensure that a non-login, non-interactive shell has a defined environment.
if [[ "$SHLVL" -eq 1 && ! -o LOGIN && -s "${ZDOTDIR:-$HOME}/.zprofile" ]]; then
  source "${ZDOTDIR:-$HOME}/.zprofile"
fi
