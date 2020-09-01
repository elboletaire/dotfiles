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

export LS_COLORS="$(vivid generate molokai)"

# Define completions
fpath=(~/.dotfiles/completion $fpath)
# Load completions
autoload -Uz compinit && compinit -i

