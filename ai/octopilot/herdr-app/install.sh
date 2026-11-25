#!/usr/bin/env bash
# Installs Octopilot's herdr-app parts: each mod folder in herdr-app/mods is
# symlinked into the app's mods (so edits here take effect), and a key opens
# the Octopilot space (herdr/open-gui.sh) in a new tab. Idempotent.
#
#   install.sh [--dir <octopilot dir>] [--dry-run] [--uninstall]
#
# --dir       the octopilot checkout the links point into (default: this one)
# --dry-run   print what would change, change nothing
# --uninstall remove the mod links and the key, when they are ours
#
# HERDR_APP_HOME picks another app home, as herdr-app does.
set -euo pipefail

KEY="ctrl-alt-o"
APP_HOME="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DRY=0
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$(cd "${2:?--dir needs a folder}" && pwd -P)"; shift ;;
    --dry-run) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) echo "usage: install.sh [--dir <octopilot dir>] [--dry-run] [--uninstall]"; exit 0 ;;
    *) echo "install.sh: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done

MODS_SRC="$DIR/herdr-app/mods"
MODS_DST="$APP_HOME/mods"
KEYS="$APP_HOME/keys.json"
# What the key runs: the launcher, as herdr-app's terminal.open takes it.
BINDING="$(jq -nc --arg script "$DIR/herdr/open-gui.sh" \
  '{command: "terminal.open", args: {argv: ["bash", $script], place: "tab"}}')"

# The mod folders this checkout ships, one path per line.
mod_folders() {
  local src
  for src in "$MODS_SRC"/*/; do
    [ -d "$src" ] && echo "${src%/}"
  done
  return 0
}

link_mods() {
  local src dst name
  # Checked first, so a refusal leaves every mod as it was.
  while IFS= read -r src; do
    [ -n "$src" ] || continue
    dst="$MODS_DST/$(basename "$src")"
    if [ -e "$dst" ] && [ ! -L "$dst" ]; then
      echo "install.sh: $dst exists and is not a symlink; move it aside to link $(basename "$src")" >&2
      return 1
    fi
  done < <(mod_folders)
  while IFS= read -r src; do
    [ -n "$src" ] || continue
    name="$(basename "$src")"
    dst="$MODS_DST/$name"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
      continue
    fi
    if [ "$DRY" -eq 1 ]; then
      echo "would link mod $name -> $src"
      continue
    fi
    mkdir -p "$MODS_DST"
    ln -sfn "$src" "$dst"
    echo "linked mod $name -> $src"
  done < <(mod_folders)
}

unlink_mods() {
  local link target
  [ -d "$MODS_DST" ] || return 0
  for link in "$MODS_DST"/*; do
    [ -L "$link" ] || continue
    target="$(readlink "$link")"
    case "$target" in
      "$MODS_SRC"/*)
        if [ "$DRY" -eq 1 ]; then echo "would unlink mod $(basename "$link")"; continue; fi
        rm "$link"
        echo "unlinked mod $(basename "$link")"
        ;;
    esac
  done
}

# Rewrites keys.json with a jq filter, after keeping a backup of it.
edit_keys() {
  local backup tmp
  backup="$KEYS.bak-octopilot.$(date +%Y%m%d%H%M%S)"
  tmp="$KEYS.tmp.$$"
  cp -p "$KEYS" "$backup"
  jq "$@" "$KEYS" > "$tmp"
  mv "$tmp" "$KEYS"
  echo "rewrote $KEYS (backup: $backup)"
  # The app reloads keys.json within a second; a rejected file leaves keys.error.
  sleep 2
  if [ -f "$APP_HOME/keys.error" ] && [ "$APP_HOME/keys.error" -nt "$backup" ]; then
    echo "install.sh: herdr-app rejected keys.json:" >&2
    cat "$APP_HOME/keys.error" >&2
    return 1
  fi
}

# The key: bound when free, left alone when it is bound to something else.
set_key() {
  local current
  if [ ! -f "$KEYS" ]; then
    # A keys file of our own would replace every default shortcut: wait for the
    # app to write its own.
    echo "install.sh: no $KEYS yet (open herdr-app once); key $KEY not bound" >&2
    return 0
  fi
  current="$(jq -c --arg k "$KEY" '.global[$k] // null' "$KEYS")"
  if [ "$UNINSTALL" -eq 1 ]; then
    if [ "$current" != "$BINDING" ]; then
      return 0
    fi
    if [ "$DRY" -eq 1 ]; then echo "would unbind $KEY"; return 0; fi
    edit_keys --arg k "$KEY" 'del(.global[$k])'
    return
  fi
  if [ "$current" = "$BINDING" ]; then
    return 0
  fi
  if [ "$current" != "null" ]; then
    echo "install.sh: $KEY is bound to $current in $KEYS; left as it is" >&2
    return 0
  fi
  if [ "$DRY" -eq 1 ]; then
    echo "would bind $KEY to $BINDING in $KEYS"
    return 0
  fi
  edit_keys --arg k "$KEY" --argjson b "$BINDING" '.global[$k] = $b'
}

if ! command -v jq >/dev/null; then
  echo "install.sh: jq is needed" >&2
  exit 1
fi

if [ "$UNINSTALL" -eq 1 ]; then
  unlink_mods
else
  link_mods
fi
set_key
