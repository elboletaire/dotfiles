#!/bin/bash

declare -r dotfiles=~/.dotfiles
declare -r oldfiles=~/old_dotfiles
declare -r exclude=("README.md" "LICENSE" "scripts" "git" "config")
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

symlink_config() {
  local config_dir=$dotfiles/config

  # Check if config directory exists in dotfiles
  if [ ! -d $config_dir ]; then
    return
  fi

  # Create ~/.config if it doesn't exist
  if [ ! -d ~/.config ]; then
    mkdir -p ~/.config
  fi

  # Create backup directory for config if needed
  local config_backup=$oldfiles/config

  # Loop through each item in the config directory
  for item in $config_dir/*; do
    if [ ! -e $item ]; then
      continue
    fi

    local item_name=$(basename $item)
    local destination=~/.config/$item_name

    # Backup existing file or directory
    if [ -f $destination -o -d $destination ]; then
      if [ ! -d $config_backup ]; then
        mkdir -p $config_backup
      fi
      mv -v $destination $config_backup/
    fi

    # Create symlink
    ln -sf $item $destination
  done
}

# Update apt packages
if ! sudo pacman -Syu; then
  echo "Cannot update pacman. ${aborting}" && exit 1
fi

# Install common required packages. We don't install git, as it's the way to
# install the dotfiles.
if ! sudo pacman -S --noconfirm curl zsh vivid vim which; then
  echo "Packages installation unsuccessful. ${aborting}" && exit 1
fi

# Git init submodules
git submodule update --init --recursive

# Make symbolic links
symlink

# Make symbolic links for config directory
symlink_config

# Change the shell of the current user to zsh
chsh ${USERNAME} --shell $(which zsh)

# Run Vundle.vim :PluginInstall cmd
vim -c 'PluginInstall' -c 'qa!'

echo "dotfiles installation was successful" && exit 0
