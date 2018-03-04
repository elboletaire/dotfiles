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
  docker run --rm -it --user $user --volume $location:/app --volume /tmp:/tmp/$(whoami) composer:latest $1
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

# Define completions
fpath=(~/.dotfiles/completion $fpath)
# Load completions
autoload -Uz compinit && compinit -i

# added by travis gem
[ -f "${HOME}/.travis/travis.sh" ] && source "${HOME}/.travis/travis.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
