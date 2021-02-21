#
# Executes commands at the start of an interactive session.
#
# Authors:
#   Sorin Ionescu <sorin.ionescu@gmail.com>
#

# Source Prezto.
if [[ -s "${ZDOTDIR:-$HOME}/.zprezto/init.zsh" ]]; then
  source "${ZDOTDIR:-$HOME}/.zprezto/init.zsh"
fi

alias sudo='sudo -E'
export GPG_TTY=$(tty)

export LS_COLORS="$(vivid generate molokai)"

if [ -d /usr/local/go/bin ]; then
    PATH="$PATH:/usr/local/go/bin"
fi

# Define completions
fpath=(~/.dotfiles/completion $fpath)
# Load completions
autoload -Uz compinit && compinit -i

