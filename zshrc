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

if [ -d ${HOME}/.cargo/bin ]; then
  PATH="$PATH:${HOME}/.cargo/bin"
fi

# Define completions
fpath=(~/.dotfiles/completion $fpath)
# Load completions
autoload -Uz compinit && compinit -i

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

autoload -U add-zsh-hook

load-nvmrc() {
  local nvmrc_path
  nvmrc_path="$(nvm_find_nvmrc)"

  if [ -n "$nvmrc_path" ]; then
    local nvmrc_node_version
    nvmrc_node_version=$(nvm version "$(cat "${nvmrc_path}")")

    if [ "$nvmrc_node_version" = "N/A" ]; then
      nvm install
      npm i -g pnpm yarn
    elif [ "$nvmrc_node_version" != "$(nvm version)" ]; then
      nvm use
    fi
  elif [ -n "$(PWD=$OLDPWD nvm_find_nvmrc)" ] && [ "$(nvm version)" != "$(nvm version default)" ]; then
    echo "Reverting to nvm default version"
    nvm use default
  fi
}

add-zsh-hook chpwd load-nvmrc
load-nvmrc


. "$HOME/.local/bin/env"

# pnpm
export PNPM_HOME="/home/elboletaire/.local/share/pnpm"
case ":$PATH:" in
  *":$PNPM_HOME:"*) ;;
  *) export PATH="$PNPM_HOME:$PATH" ;;
esac
# pnpm end
