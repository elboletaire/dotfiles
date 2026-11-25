#!/usr/bin/env bash
# Installs Octopilot's herdr-app parts: each mod folder in herdr-app/mods is
# symlinked into the app's mods (edits here take effect at once), and
# programs.json gets an Octopilot entry, which the launcher mod runs.
#
#   install.sh [--dir <octopilot dir>] [--key] [--dry-run] [--uninstall]
#
# --dir       the octopilot checkout the links and the entry point into (default: this one)
# --key       also bind ctrl-alt-o in keys.json (not on by default: see README)
# --dry-run   print what would change, change nothing
# --uninstall remove the mod links, the program entry and the key, when they are ours
#
# HERDR_APP_HOME picks another app home, as herdr-app does.
set -euo pipefail

KEY="ctrl-alt-o"
APP_HOME="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DRY=0
UNINSTALL=0
WITH_KEY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$(cd "${2:?--dir needs a folder}" && pwd -P)"; shift ;;
    --key) WITH_KEY=1 ;;
    --dry-run) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) echo "usage: install.sh [--dir <octopilot dir>] [--key] [--dry-run] [--uninstall]"; exit 0 ;;
    *) echo "install.sh: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done

MODS_SRC="$DIR/herdr-app/mods"
MODS_DST="$APP_HOME/mods"
PROGRAMS="$APP_HOME/programs.json"
KEYS="$APP_HOME/keys.json"
LAUNCHER="$DIR/herdr/open-gui.sh"

# What we wrote, recognised by shape, so a checkout that moved updates it.
# Both are jq predicates on one value.
OURS_PROGRAM='type == "object" and ((.run // []) | length == 3 and .[0] == "bash"
  and (.[1] | type == "string" and endswith("/herdr/open-gui.sh")) and .[2] == "--close-launcher")'
OURS_BINDING='type == "object" and .command == "terminal.open" and
  ((.args.argv // []) | length >= 2 and .[0] == "bash"
  and (.[1] | type == "string" and endswith("/herdr/open-gui.sh")))'

# A herdr-app JSON file's content, or an empty object when it does not exist yet.
read_json() {
  if [ -f "$1" ]; then cat "$1"; else echo '{}'; fi
}

# The value at a jq path in a file (null when absent), failing when the file is
# not valid JSON: herdr-app would reject it too.
value_at() {
  read_json "$1" | jq -c "$2" || {
    echo "install.sh: $1 is not valid JSON; left as it is" >&2
    return 1
  }
}

# Rewrites a herdr-app JSON file with a jq filter, keeping a backup of the old
# one, then checks the <name>.error herdr-app writes when it rejects the file.
edit_json() {
  local file=$1 filter=$2 backup="" tmp errfile
  shift 2
  errfile="${file%.json}.error"
  tmp="$file.tmp.$$"
  if [ -f "$file" ]; then
    backup="$file.bak-octopilot.$(date +%Y%m%d%H%M%S)"
    cp -p "$file" "$backup"
  fi
  read_json "$file" | jq "$@" "$filter" > "$tmp"
  mv "$tmp" "$file"
  echo "wrote $file${backup:+ (backup: $backup)}"
  # The app reloads within a second or two.
  sleep 2
  if [ -n "$backup" ] && [ -f "$errfile" ] && [ "$errfile" -nt "$backup" ]; then
    echo "install.sh: herdr-app rejected $file:" >&2
    cat "$errfile" >&2
    return 1
  fi
}

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

# programs.json's octopilot entry: what the launcher mod's palette entry and
# the menus start. Other entries stay as they are.
set_program() {
  local current entry
  current="$(value_at "$PROGRAMS" '.programs.octopilot // null')" || return 1
  if [ "$UNINSTALL" -eq 1 ]; then
    if [ "$(jq -n --argjson v "$current" "\$v | select($OURS_PROGRAM) | true")" != "true" ]; then
      return 0
    fi
    if [ "$DRY" -eq 1 ]; then echo "would remove the octopilot program"; return 0; fi
    edit_json "$PROGRAMS" 'del(.programs.octopilot)'
    return
  fi
  entry="$(jq -nc --arg s "$LAUNCHER" '{name: "Octopilot", run: ["bash", $s, "--close-launcher"]}')"
  if [ "$current" = "$entry" ]; then return 0; fi
  if [ "$current" != "null" ] && [ "$(jq -n --argjson v "$current" "\$v | select($OURS_PROGRAM) | true")" != "true" ]; then
    echo "install.sh: programs.json has its own octopilot entry; left as it is" >&2
    return 0
  fi
  if [ "$DRY" -eq 1 ]; then echo "would set the octopilot program to $entry"; return 0; fi
  edit_json "$PROGRAMS" '.programs.octopilot = $e' --argjson e "$entry"
}

# The ctrl-alt-o binding, only with --key; removed by --uninstall when ours.
set_key() {
  local current binding
  if [ "$UNINSTALL" -eq 0 ] && [ "$WITH_KEY" -eq 0 ]; then return 0; fi
  current="$(value_at "$KEYS" ".global[\"$KEY\"] // null")" || return 1
  if [ "$UNINSTALL" -eq 1 ]; then
    if [ "$(jq -n --argjson v "$current" "\$v | select($OURS_BINDING) | true")" != "true" ]; then
      return 0
    fi
    if [ "$DRY" -eq 1 ]; then echo "would unbind $KEY"; return 0; fi
    edit_json "$KEYS" 'del(.global[$k])' --arg k "$KEY"
    return
  fi
  if [ ! -f "$KEYS" ]; then
    # A keys file of our own would replace every default shortcut.
    echo "install.sh: no $KEYS yet (open herdr-app once); key $KEY not bound" >&2
    return 0
  fi
  binding="$(jq -nc --arg s "$LAUNCHER" \
    '{command: "terminal.open", args: {argv: ["bash", $s], place: "tab"}}')"
  if [ "$current" = "$binding" ]; then return 0; fi
  if [ "$current" != "null" ] && [ "$(jq -n --argjson v "$current" "\$v | select($OURS_BINDING) | true")" != "true" ]; then
    echo "install.sh: $KEY is bound to $current in $KEYS; left as it is" >&2
    return 0
  fi
  if [ "$DRY" -eq 1 ]; then echo "would bind $KEY to $binding"; return 0; fi
  edit_json "$KEYS" '.global[$k] = $b' --arg k "$KEY" --argjson b "$binding"
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
set_program
set_key
