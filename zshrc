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

_composer() {
  location=$(pwd -P)
  user=$(id -u):$(id -g)
  docker run --rm -it --user $user --volume $SSH_AUTH_SOCK:/ssh-auth.sock --env SSH_AUTH_SOCK=/ssh-auth.sock --volume $location:/app --volume /tmp:/tmp/$(whoami) --volume /etc/passwd:/etc/passwd:ro --volume /etc/group:/etc/group:ro composer:latest "$@" --ignore-platform-reqs --no-scripts
}

# Customize to your needs...
alias sudo='sudo -E'
alias composer=_composer

# transfer.sh
transfer() {
    # write to output to tmpfile because of progress bar
    tmpfile=$( mktemp -t transferXXX )
    curl --progress-bar --upload-file $1 https://transfer.sh/$(basename $1) >> $tmpfile
    cat $tmpfile
    echo
    rm -f $tmpfile
}

alias transfer=transfer

export PATH="$PATH:$HOME/.rvm/bin" # Add RVM to PATH for scripting

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

# Define completions
fpath=(~/.dotfiles/completion $fpath)
# Load completions
autoload -Uz compinit && compinit -i

# added by travis gem
[ -f "${HOME}/.travis/travis.sh" ] && source "${HOME}/.travis/travis.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
