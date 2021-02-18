#
# Executes commands at the start of an interactive session.
#
# Authors:
#   Sorin Ionescu <sorin.ionescu@gmail.com>
#

# Define completions
fpath+=(${HOME}/.dotfiles/completion/_docker-compose)
fpath+=(${HOME}/.dotfiles/completion/_buffalo)
# Load completions
autoload -U compinit && compinit

# Source Prezto.
if [[ -s "${ZDOTDIR:-$HOME}/.zprezto/init.zsh" ]]; then
  source "${ZDOTDIR:-$HOME}/.zprezto/init.zsh"
fi

_composer() {
  local location=$(pwd -P)
  local user=$(id -u):$(id -g)
  local username=$(whoami)
  docker run --rm -it --user $user --volume $SSH_AUTH_SOCK:/ssh-auth.sock --env SSH_AUTH_SOCK=/ssh-auth.sock --volume $location:/app --volume /tmp:/tmp/$username --volume /etc/passwd:/etc/passwd:ro --volume /etc/group:/etc/group:ro composer:latest "$@" --ignore-platform-reqs --no-scripts
}

if [ -x /usr/bin/bat ]; then
  alias cat='bat'
fi

alias sudo='sudo -E'

if [ -d "${HOME}/.rvm/bin" ]; then
  export PATH="$PATH:$HOME/.rvm/bin" # Add RVM to PATH for scripting
fi

if [ -d "$HOME/.yarn/bin" ]; then
  export PATH="$PATH:$HOME/.yarn/bin"
fi


if [ -d "${HOME}/src/golang" ]; then
  export PATH="$PATH:/usr/local/go/bin"
  export GOPATH="$HOME/src/golang"
  export PATH="$PATH:$GOPATH/bin"
fi

# Add android studio required vars..
if [ -d "${HOME}/.Android" ]; then
  export ANDROID_HOME=${HOME}/.Android/Sdk
  export PATH=${PATH}:${ANDROID_HOME}/tools
  export PATH=${PATH}:${ANDROID_HOME}/platform-tools
fi

# Add composer path if binary path is found where expected
if [ -d "${HOME}/.config/composer/vendor/bin" ]; then
  export PATH=${PATH}:${HOME}/.config/composer/vendor/bin
fi

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" # This loads nvm

# place this after nvm initialization!
autoload -U add-zsh-hook
load-nvmrc() {
  local node_version="$(nvm version)"
  local nvmrc_path="$(nvm_find_nvmrc)"

  if [ -n "$nvmrc_path" ]; then
    local nvmrc_node_version=$(nvm version "$(cat "${nvmrc_path}")")

    if [ "$nvmrc_node_version" = "N/A" ]; then
      nvm install
    elif [ "$nvmrc_node_version" != "$node_version" ]; then
      nvm use
    fi
  elif [ "$node_version" != "$(nvm version default)" ]; then
    echo "Reverting to nvm default version"
    nvm use default
  fi
}
add-zsh-hook chpwd load-nvmrc
load-nvmrc


# added by travis gem
[ -f "${HOME}/.travis/travis.sh" ] && source "${HOME}/.travis/travis.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
