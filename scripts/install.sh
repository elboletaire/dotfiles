#!/bin/bash

declare -r dotfiles=~/.dotfiles
declare -r oldfiles=~/old_dotfiles
declare -r exclude=("README.md" "LICENSE" "scripts" "git" "config" "ai")
declare -r aborting="Aborting dotfiles installation..."
OS=$(uname -s)

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
    # Skip if it's already the intended symlink (keeps re-runs cruft-free)
    if [ -L "$destination" ] && [ "$(readlink "$destination")" = "$file" ]; then
      continue
    fi
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

    # Skip if it's already the intended symlink (keeps re-runs cruft-free)
    if [ -L "$destination" ] && [ "$(readlink "$destination")" = "$item" ]; then
      continue
    fi

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

install_rtk() {
  # rtk (Rust Token Killer): CLI proxy that compresses command output before it
  # reaches the assistant. https://github.com/rtk-ai/rtk
  # Pass "update" to force an upgrade even when rtk is already installed.
  local mode=$1

  if [[ "$mode" == "update" ]]; then
    if [[ "$OS" == "Darwin" ]]; then
      brew upgrade rtk || brew install rtk
    else
      curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
    fi
  elif command -v rtk &>/dev/null; then
    echo "rtk already installed ($(rtk --version))"
  elif [[ "$OS" == "Darwin" ]]; then
    brew install rtk
  else
    curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
  fi

  # Wire the hook into Claude Code and Pi. This also (re)generates ~/.claude/RTK.md,
  # which is why RTK.md is not tracked in the repo. Run before symlink_ai so rtk
  # never edits our tracked CLAUDE.md symlink.
  if command -v rtk &>/dev/null; then
    rtk init -g --auto-patch            # Claude Code
    rtk init -g --agent pi --auto-patch # Pi
  else
    echo "rtk not on PATH after install; skipping hook init"
  fi
}

# Symlink a single AI-config path into place, backing up whatever is already there.
link_ai() {
  local src=$1 dest=$2
  mkdir -p "$(dirname "$dest")"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    return
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    mkdir -p "$oldfiles"
    mv -v "$dest" "$oldfiles/"
  fi
  ln -s "$src" "$dest"
}

symlink_ai() {
  local ai=$dotfiles/ai

  # Prompts: single source of truth shared by Pi prompts and Claude commands.
  link_ai "$ai/prompts" ~/.pi/agent/prompts
  link_ai "$ai/prompts" ~/.claude/commands

  # Pi subagent definitions and global instructions.
  link_ai "$ai/pi/agents" ~/.pi/agent/agents
  link_ai "$ai/pi/AGENTS.md" ~/.pi/agent/AGENTS.md

  # Claude global instructions.
  link_ai "$ai/claude/CLAUDE.md" ~/.claude/CLAUDE.md

  # Skills: rebuild the shared ~/.agents hub from the committed lock. The global
  # lock has no built-in restore, so re-add each skill from its recorded source.
  if command -v npx &>/dev/null && command -v node &>/dev/null; then
    node -e '
      const path = require("path");
      const skills = require(path.resolve(process.argv[1])).skills || {};
      for (const [name, s] of Object.entries(skills)) {
        if (s.source) console.log(s.source + "\t" + name);
      }
    ' "$ai/skills/skill-lock.json" | while IFS=$'\t' read -r src name; do
      echo ">> skills add $src --skill $name"
      npx --yes skills add "$src" --skill "$name" -g -y || echo "  (failed: $name)"
    done
  else
    echo "node/npx not found; skipping skills restore."
    echo "Install Node, then re-run: bash $dotfiles/scripts/install.sh"
  fi
}

update_skills() {
  # Bump the shared ~/.agents skills hub to latest and re-sync the lock into the
  # repo so the version bump shows up as a reviewable git change.
  if ! command -v npx &>/dev/null; then
    echo "npx not found; skipping skills update."
    return
  fi
  npx --yes skills update -g -y
  if [ -f ~/.agents/.skill-lock.json ]; then
    cp ~/.agents/.skill-lock.json "$dotfiles/ai/skills/skill-lock.json"
    echo "Synced skill-lock.json into the repo (review & commit the bump)."
  fi
}

install_packages() {
  if [[ "$OS" == "Darwin" ]]; then
    # macOS: install Homebrew if not present
    if ! command -v brew &>/dev/null; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    if ! brew update; then
      echo "Cannot update Homebrew. ${aborting}" && exit 1
    fi
    # curl, zsh, vim, and which are all pre-installed on macOS; only vivid needs Homebrew.
    if ! brew install vivid; then
      echo "Packages installation unsuccessful. ${aborting}" && exit 1
    fi
  else
    # Linux (Arch): use pacman
    if ! sudo pacman -Syu; then
      echo "Cannot update pacman. ${aborting}" && exit 1
    fi
    # Install common required packages. We don't install git, as it's the way to
    # install the dotfiles.
    if ! sudo pacman -S --noconfirm yay curl zsh vivid vim which; then
      echo "Packages installation unsuccessful. ${aborting}" && exit 1
    fi
    if ! yay -S --noconfirm obscura-browser-bin; then
      echo "Could not install AUR packages. ${aborting}" && exit 1
    fi
  fi
}

do_install() {
  install_packages
  git submodule update --init --recursive
  symlink
  symlink_config
  # Install rtk and wire its hook into Claude Code and Pi (before symlink_ai)
  install_rtk
  # Symlink AI assistant config (prompts, agents, instructions) and restore skills
  symlink_ai
  # Change the shell of the current user to zsh
  chsh -s "$(which zsh)"
  # Run Vundle.vim :PluginInstall cmd
  vim -c 'PluginInstall' -c 'qa!'
  echo "dotfiles installation was successful"
}

do_update() {
  # Lightweight: no system packages, no submodule version bump.
  git submodule update --init --recursive
  symlink
  symlink_config
  install_rtk update
  symlink_ai
  update_skills
  echo "dotfiles update complete"
}

do_update_ai() {
  # AI-only fast path: refresh rtk, its hooks, the AI symlinks and the skills.
  install_rtk update
  symlink_ai
  update_skills
  echo "AI stack update complete"
}

case "${1:-install}" in
  install) do_install ;;
  update)  do_update ;;
  ai)      do_update_ai ;;
  *) echo "usage: $(basename "$0") [install|update|ai]" && exit 1 ;;
esac
