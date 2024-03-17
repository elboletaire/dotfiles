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
alias jprobe='ffprobe -v error -print_format json -show_format -show_streams'
export GPG_TTY=$(tty)

export MAKEFLAGS="-j10"

export LS_COLORS="$(vivid generate molokai)"

if [ -d /usr/local/go/bin ]; then
    PATH="$PATH:/usr/local/go/bin"
    PATH="$PATH:${HOME}/go/bin"
fi

if [ -d ${HOME}/go/bin ]; then
  PATH="$PATH:${HOME}/go/bin"
fi

# Define completions
fpath=(~/.dotfiles/completion $fpath)
# Load completions
autoload -Uz compinit && compinit -i


export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
