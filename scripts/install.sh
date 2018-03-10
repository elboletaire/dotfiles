#!/bin/bash

declare -r dotfiles=~/.dotfiles
declare -r oldfiles=~/old_dotfiles
declare -r exclude=("README.md" "LICENSE" "scripts" "git-templates")
declare -r aborting="Aborting dotfiles installation..."

backup_dotfile() {
  if [ ! -d $oldfiles ]; then
    mkdir -p $oldfiles
  fi
  mv -v $1 $oldfiles
}

in_array() {
  local e
  for e in "${@:2}"; do [[ "$e" == "$1" ]] && return 1; done
  return 0
}

symlink() {
  for file in $dotfiles/*; do
    filename=$(basename $file)
    in_array $filename ${exclude[@]}
    if [ $? = 1 ]; then
      continue
    fi
    destination=~/.$filename
    if [ -f $destination -o -d $destination ]; then
      backup_dotfile $destination
    fi
    ln -sf $file $destination
  done
}

# Create cygwin passwd file
mkpasswd > /etc/passwd

# Git init submodules
git submodule update --init --recursive

# Make symbolic links
symlink

# Change the shell of the current user to zsh
chsh ${USERNAME} --shell $(which zsh)

# Run Vundle.vim :PluginInstall cmd
vim -c 'PluginInstall' -c 'qa!'

# Source .zshrc to load NVM configuration
source ~/.zshrc

if [ $(command -v nvm) != 'nvm' ]; then
  echo "NVM not detected" && exit 1
fi

echo "dotfiles installation was successful" && exit 0
