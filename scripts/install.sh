#!/bin/bash

declare -r dotfiles=~/.dotfiles
declare -r oldfiles=~/old_dotfiles
declare -r exclude=("README.md" "LICENSE" "scripts" "git" "config" "ai" "AGENTS.md" "CLAUDE.md")
declare -r aborting="Aborting dotfiles installation..."
# When set, link_ai replaces existing paths instead of moving them to $oldfiles.
no_backup=0
OS=$(uname -s)
# herdr and herdr-app install into ~/.local/bin, which must be on PATH for the
# command -v checks below.
export PATH="$HOME/.local/bin:$PATH"

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

  # Items managed elsewhere: herdr's dir also holds its live state, so
  # link_herdr_config links only its config.toml.
  local -r managed_elsewhere=(herdr)

  # Loop through each item in the config directory
  for item in $config_dir/*; do
    if [ ! -e $item ]; then
      continue
    fi

    local item_name=$(basename $item)
    in_array $item_name "${managed_elsewhere[@]}" || continue
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

install_nvm() {
  if [ ! -s "$HOME/.nvm/nvm.sh" ]; then
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/HEAD/install.sh | bash
  fi
  export NVM_DIR="$HOME/.nvm"
  # shellcheck disable=SC1091
  \. "$NVM_DIR/nvm.sh"
  nvm install --lts
  nvm alias default lts/*
  nvm use default
}

install_ai_agents() {
  curl -fsSL https://claude.ai/install.sh | bash
  curl -fsSL https://pi.dev/install.sh | sh
}

_run_remote_installer() {
  # Runs a downloaded installer with sh, but only when the download worked: a
  # piped curl would hide its failure behind sh's exit status.
  local url=$1 tmp_installer rc
  tmp_installer="$(mktemp)" || return 1
  if ! curl -fsSL "$url" -o "$tmp_installer"; then
    echo "ERROR: Failed to download $url" >&2
    rm -f "$tmp_installer"
    return 1
  fi
  sh "$tmp_installer"
  rc=$?
  rm -f "$tmp_installer"
  return $rc
}

# APM (Agent Package Manager) installs the skills from ai/apm.yml.
# https://github.com/microsoft/apm
apm_min_version=0.39.0

_apm_version() {
  # The installed APM version (e.g. 0.39.0); empty when apm is missing.
  apm --version 2>/dev/null | sed -n 's/.*version \([0-9][0-9.]*\).*/\1/p' | head -1
}

_apm_at_least() {
  # True when version $1 is $2 or newer.
  [ "$(printf '%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}

install_apm() {
  # Older releases cannot do the locked installs install_skills relies on, so
  # an older apm is upgraded on every path.
  local current
  current=$(_apm_version)
  if [ -n "$current" ] && _apm_at_least "$current" "$apm_min_version"; then
    echo "apm already installed ($current)"
    return 0
  fi
  if [ -n "$current" ]; then
    echo "apm $current is older than $apm_min_version; upgrading"
  fi
  if [[ "$OS" == "Darwin" ]] && brew list --formula apm &>/dev/null; then
    brew upgrade microsoft/apm/apm || return 1
  elif [[ "$OS" == "Darwin" ]] && [ -z "$current" ]; then
    brew install microsoft/apm/apm || return 1
  else
    # Downloaded first, so a failed download is not hidden behind a pipe.
    local tmp_installer install_rc
    tmp_installer="$(mktemp)"
    if ! curl -fsSL https://aka.ms/apm-unix -o "$tmp_installer"; then
      echo "ERROR: Failed to download APM installer" >&2
      rm -f "$tmp_installer"
      return 1
    fi
    bash "$tmp_installer"
    install_rc=$?
    rm -f "$tmp_installer"
    [ "$install_rc" -eq 0 ] || return "$install_rc"
  fi
  current=$(_apm_version)
  if [ -z "$current" ] || ! _apm_at_least "$current" "$apm_min_version"; then
    echo "ERROR: apm $apm_min_version or newer is required (found: ${current:-none})" >&2
    return 1
  fi
}

# Copies the tracked manifest and lock into the global APM dir as regular files:
# a symlink there would let APM write through it into the repo.
_copy_apm_files() {
  local from=$1 to=$2 f
  for f in apm.yml apm.lock.yaml; do
    rm -f "$to/$f" && cp "$from/$f" "$to/$f" || return 1
  done
}

# Skill dir names that the given APM locks deploy under ~/.agents/skills or
# ~/.claude/skills.
_apm_skill_names() {
  grep -hE '^  - \.(agents|claude)/skills/[^/]+' "$@" 2>/dev/null |
    sed -E 's#^  - \.(agents|claude)/skills/([^/]+).*#\2#' | sort -u
}

# Once the old global manifest lists ai/ as a local package (0.33 wrote it as an
# absolute path ending in /ai), its deployed skills block the new install: APM
# refuses to replace files it does not manage. Moves those skills aside, and
# the 0.33 hook files, to the legacy backup so APM deploys them fresh.
_retire_local_apm_package() {
  local apm_home=$1 new_lock=$2
  local backup=$oldfiles/legacy-skills-$(date +%Y%m%d) name root path
  grep -qE '^[[:space:]]*-[[:space:]]+/([^[:space:]]*/)?ai/?[[:space:]]*$' "$apm_home/apm.yml" 2>/dev/null || return 0
  echo "Retiring the local dotfiles APM package: its skills move aside"
  apm_retired_backup=$backup
  for path in "$HOME/.claude/apm-hooks.json" "$HOME/.claude/hooks/contributing"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      _move_legacy "$path" "$backup"
    fi
  done
  for name in $(_apm_skill_names "$apm_home/apm.lock.yaml" "$new_lock"); do
    for root in .agents .claude; do
      path="$HOME/$root/skills/$name"
      if [ -e "$path" ] || [ -L "$path" ]; then
        _move_legacy "$path" "$backup"
      fi
    done
  done
}

install_skills() {
  # Installs the skills from ai/apm.yml globally. The locked commits decide what
  # gets installed, so this reproduces ai/apm.lock.yaml; only skills-bump moves them.
  local ai=$dotfiles/ai apm_home=$HOME/.apm
  if ! _apm_at_least "$(_apm_version)" "$apm_min_version"; then
    echo "ERROR: apm $apm_min_version or newer is required; run 'install.sh ai' first" >&2
    return 1
  fi
  apm_retired_backup=""
  mkdir -p "$apm_home" || return 1
  _retire_local_apm_package "$apm_home" "$ai/apm.lock.yaml"
  _copy_apm_files "$ai" "$apm_home" || return 1
  if ! (cd "$apm_home" && apm install -g --target agent-skills,claude); then
    echo "ERROR: apm install -g failed; ai/ unchanged" >&2
    if [ -n "$apm_retired_backup" ]; then
      echo "ERROR: the skills moved by the one-time migration are in $apm_retired_backup;" >&2
      echo "ERROR: fix the error above and run 'install.sh ai' again to deploy them" >&2
    fi
    return 1
  fi
  # APM rewrites the lock only when apm.yml changed; the copy in ai/ follows it.
  if ! cmp -s "$apm_home/apm.lock.yaml" "$ai/apm.lock.yaml"; then
    cp "$apm_home/apm.lock.yaml" "$ai/apm.lock.yaml" || return 1
    echo "NOTE: ai/apm.lock.yaml changed; review and commit it"
  fi
}

skills_bump() {
  # The only path that moves skill versions: each dependency goes to the latest
  # commit of its ref. ai/ is replaced only after apm update succeeds.
  local ai=$dotfiles/ai apm_home=$HOME/.apm
  mkdir -p "$apm_home" || return 1
  _retire_local_apm_package "$apm_home" "$ai/apm.lock.yaml"
  _cleanup_legacy_skills
  _copy_apm_files "$ai" "$apm_home" || return 1
  if ! (cd "$apm_home" && apm update -g --yes --target agent-skills,claude); then
    echo "ERROR: apm update -g failed; ai/ unchanged" >&2
    return 1
  fi
  if ! { cp "$apm_home/apm.yml" "$ai/apm.yml" && cp "$apm_home/apm.lock.yaml" "$ai/apm.lock.yaml"; }; then
    echo "ERROR: could not write ai/; restore it from git" >&2
    return 1
  fi
  # Shows the change when dotfiles is a git checkout; otherwise nothing to show.
  if ! git -C "$dotfiles" rev-parse --git-dir &>/dev/null; then
    echo "Updated ai/apm.yml and ai/apm.lock.yaml"
  elif git -C "$dotfiles" diff --quiet -- ai/; then
    echo "No skill version moved."
  else
    git -C "$dotfiles" diff --stat -- ai/
  fi
}

install_herdr() {
  # herdr: terminal workspace manager for coding agents. Hosts Octopilot's
  # workers, orchestrator and dashboard. https://herdr.dev
  # Pass "update" to upgrade even when herdr is already installed.
  local mode=${1:-} agent

  if command -v herdr &>/dev/null; then
    if [[ "$mode" == "update" ]]; then
      _update_herdr
    else
      echo "herdr already installed ($(herdr --version 2>/dev/null || echo present))"
    fi
  elif [[ "$OS" == "Darwin" ]]; then
    brew install herdr
  else
    _run_remote_installer https://herdr.dev/install.sh ||
      echo "WARNING: herdr install failed (see above)" >&2
  fi
  command -v herdr &>/dev/null || return 0

  # Agent-state hooks: what lets herdr tell working/blocked/done apart and
  # resume conversations after a restart. Only for agents that are installed
  # and whose integration is missing or outdated.
  for agent in claude pi; do
    command -v "$agent" &>/dev/null || continue
    if ! herdr integration status 2>/dev/null | grep -q "^$agent: current"; then
      herdr integration install "$agent"
    fi
  done
}

_update_herdr() {
  # Upgrades herdr with whoever installed it, so no second copy appears: the
  # package manager that owns the binary, else herdr's own updater.
  if [[ "$OS" == "Darwin" ]]; then
    # Brew owns herdr only when the herdr on PATH is Homebrew's link to it.
    if [ "$(command -v herdr)" -ef "$(brew --prefix 2>/dev/null)/bin/herdr" ]; then
      brew upgrade herdr
    else
      herdr update
    fi
  elif pacman -Qo "$(command -v herdr)" &>/dev/null; then
    # AUR, like obscura-browser-bin: pacman owns the binary and its upgrades.
    yay -S --needed --noconfirm herdr-bin
  else
    herdr update
  fi
}

install_herdr_app() {
  # herdr-app: the Herdr desktop app, with herdr-core (hc) beside it if none is
  # installed yet. "update" reruns its installer only when the version changed.
  # Arch needs the app's runtime libraries, installed only with the app.
  local mode=${1:-}
  if ! command -v herdr-app &>/dev/null; then
    if [[ "$OS" != "Darwin" ]]; then
      sudo pacman -S --needed --noconfirm vulkan-icd-loader mesa libxkbcommon-x11 wayland ||
        echo "WARNING: could not install herdr-app's runtime libraries" >&2
    fi
  elif [[ "$mode" != "update" ]]; then
    echo "herdr-app already installed"
    return 0
  elif ! _herdr_app_outdated; then
    return 0
  fi
  _run_remote_installer https://releases.herdr.dev/app/install.sh ||
    echo "WARNING: herdr-app install failed (see above)" >&2
}

_herdr_app_outdated() {
  # True when the published herdr-app version differs from the installed one.
  # False when offline, and on macOS while Herdr.app runs: its installer would
  # replace the running app.
  local latest installed
  if ! latest=$(curl -fsSL --max-time 15 https://releases.herdr.dev/app/latest.json 2>/dev/null); then
    echo "herdr-app: could not reach releases.herdr.dev; skipping the update"
    return 1
  fi
  latest=$(printf '%s' "$latest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])') ||
    return 1
  # "herdr-app --version" prints "herdr-app <version>".
  installed=$(herdr-app --version 2>/dev/null | awk '{ print $NF }')
  if [[ "$installed" == "$latest" ]]; then
    echo "herdr-app $installed is current"
    return 1
  fi
  if [[ "$OS" == "Darwin" ]] && pgrep -x Herdr &>/dev/null; then
    echo "herdr-app $installed is installed and $latest is out, but Herdr is running; quit it and rerun to update"
    return 1
  fi
  return 0
}

# Session managers replaced by herdr (agent-deck, agent-of-empires, aoe) and the
# fleet skill that drove agent-deck. Packages are uninstalled, binaries deleted,
# config and state go under ~/old_dotfiles. Prints only what it did.
cleanup_legacy() {
  local backup=$oldfiles/legacy-session-managers-$(date +%Y%m%d)
  local bin f skill link

  _uninstall_legacy_packages

  for bin in "$HOME/.local/bin" "$HOME/bin" "$HOME/.cargo/bin" "$HOME/go/bin"; do
    for f in "$bin/agent-deck" "$bin/aoe" "$bin/aoe (deleted)"; do
      if [ -e "$f" ] || [ -L "$f" ]; then
        rm -f "$f"
        echo "Removed $f"
      fi
    done
  done

  for f in "$HOME/.config/agent-deck" "$HOME/.config/agent-of-empires" "$HOME/.config/aoe" \
    "$HOME/.local/share/agent-deck" "$HOME/.local/share/agent-of-empires" "$HOME/.local/share/aoe" \
    "$HOME/.local/state/agent-deck" "$HOME/.local/state/agent-of-empires" "$HOME/.local/state/aoe" \
    "$HOME/.cache/agent-deck" "$HOME/.cache/agent-of-empires" "$HOME/.cache/aoe" \
    "$HOME/.agent-deck" "$HOME/.aoe" \
    "$HOME/Library/Application Support/agent-deck" "$HOME/Library/Application Support/agent-of-empires" \
    "$HOME/Library/Application Support/aoe"; do
    if [ -e "$f" ] || [ -L "$f" ]; then
      _move_legacy "$f" "$backup"
    fi
  done

  # Only agent-deck's own block: a file with the user's lines too is theirs.
  if [ -f "$HOME/.tmux.conf" ] && _is_agent_deck_tmux_conf "$HOME/.tmux.conf"; then
    _move_legacy "$HOME/.tmux.conf" "$backup"
  elif [ -f "$HOME/.tmux.conf" ] && grep -q '^# agent-deck configuration$' "$HOME/.tmux.conf"; then
    echo "NOTE: $HOME/.tmux.conf has agent-deck's block next to other lines; left as is"
  fi

  # The fleet and agent-deck skills are removed only where they name agent-deck.
  for skill in "$HOME/.claude/skills/fleet" "$HOME/.agents/skills/fleet" \
    "$HOME/.claude/skills/agent-deck" "$HOME/.agents/skills/agent-deck"; do
    if [ -f "$skill/SKILL.md" ] && grep -q agent-deck "$skill/SKILL.md"; then
      rm -rf "$skill"
      echo "Removed $skill"
    fi
  done

  # Pi's links: fleet's once its target is gone, agent-deck's when dangling or
  # pointing at ~/.agents/skills/agent-deck.
  link=$HOME/.pi/agent/skills/fleet
  if [ -L "$link" ] && [ ! -e "$link" ]; then
    rm -f "$link"
    echo "Removed $link"
  fi
  link=$HOME/.pi/agent/skills/agent-deck
  if [ -L "$link" ] && { [ ! -e "$link" ] || [ "$link" -ef "$HOME/.agents/skills/agent-deck" ]; }; then
    rm -f "$link"
    echo "Removed $link"
  fi
  _cleanup_legacy_skills
  return 0
}

# Hand-installed skills that APM now deploys or that were retired. Each one is
# removed only where APM's global lock does not deploy it.
legacy_skills=(aoe aoe-fleet impeccable graphic-designer effective-print-design
  resume-generator brag brag-slim tsdown vocdoni-sdk davinci-sdk
  vocdoni-ballot-protocol agent-browser create-readme)

# True when ~/.apm/apm.lock.yaml deploys $1, a path relative to $HOME.
_apm_deploys() {
  grep -qxF -- "  - $1" "$HOME/.apm/apm.lock.yaml" 2>/dev/null
}

_cleanup_legacy_skills() {
  local backup=$oldfiles/legacy-skills-$(date +%Y%m%d)
  local name root link target agents_skills

  # Unmanaged copies go to $backup; APM would refuse to overwrite them.
  for name in "${legacy_skills[@]}"; do
    for root in "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.pi/agent/skills"; do
      link="$root/$name"
      if [ ! -e "$link" ] && [ ! -L "$link" ]; then
        continue
      fi
      if _apm_deploys "${root#"$HOME"/}/$name"; then
        continue
      fi
      if [ -L "$link" ]; then
        rm -f "$link"
        echo "Removed $link"
      else
        _move_legacy "$link" "$backup"
      fi
    done
  done

  # Dangling links are left by the skills removed above or by older installs.
  for root in "$HOME/.pi/agent/skills" "$HOME/.claude/skills"; do
    [ -d "$root" ] || continue
    for link in "$root"/*; do
      if [ -L "$link" ] && [ ! -e "$link" ]; then
        rm -f "$link"
        echo "Removed dangling $link"
      fi
    done
  done

  # Pi reads ~/.agents/skills natively, so its per-skill links into it are redundant.
  agents_skills=$(cd -P "$HOME/.agents/skills" 2>/dev/null && pwd) || agents_skills=""
  if [ -n "$agents_skills" ]; then
    for link in "$HOME/.pi/agent/skills"/*; do
      [ -L "$link" ] && [ -e "$link" ] || continue
      target=$(cd -P "$link" 2>/dev/null && pwd) || continue
      if [[ "$target" == "$agents_skills"/* ]]; then
        rm -f "$link"
        echo "Removed $link (Pi reads ~/.agents/skills)"
      fi
    done
  fi

  # The skills CLI's lock is stale once APM owns the skills.
  if [ -e "$HOME/.agents/.skill-lock.json" ] || [ -L "$HOME/.agents/.skill-lock.json" ]; then
    _move_legacy "$HOME/.agents/.skill-lock.json" "$backup"
  fi
}

_uninstall_legacy_packages() {
  # Packages that installed aoe or agent-deck; each is removed only when present.
  local pkg installed=()
  if [[ "$OS" == "Darwin" ]]; then
    command -v brew &>/dev/null || return 0
    for pkg in aoe agent-deck; do
      if brew list --formula "$pkg" &>/dev/null; then
        brew uninstall --formula "$pkg" && echo "Uninstalled brew formula $pkg" ||
          echo "WARNING: could not uninstall brew formula $pkg" >&2
      fi
    done
  elif command -v pacman &>/dev/null; then
    for pkg in aoe agent-of-empires agent-deck; do
      pacman -Qq "$pkg" &>/dev/null && installed+=("$pkg")
    done
    if [ "${#installed[@]}" -gt 0 ]; then
      sudo pacman -Rns --noconfirm "${installed[@]}" && echo "Removed packages: ${installed[*]}" ||
        echo "WARNING: could not remove packages: ${installed[*]}" >&2
    fi
  fi
}

_move_legacy() {
  # Moves $1 under $2, keeping its path relative to $HOME so names never clash.
  local src=$1 dest
  dest=$2/${1#"$HOME"/}
  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    dest=$dest.$(date +%H%M%S)
  fi
  mv "$src" "$dest"
  echo "Moved $src -> $dest"
}

_is_agent_deck_tmux_conf() {
  # True when the file holds agent-deck's installer block and nothing else.
  grep -q '^# Added by agent-deck installer' "$1" || return 1
  awk '
    /^# agent-deck configuration$/ { inblock = 1; next }
    /^# End agent-deck configuration$/ { inblock = 0; ended = 1; next }
    !inblock && NF { extra = 1 }
    END { exit (extra || !ended || inblock) }
  ' "$1"
}

install_uv() {
  # uv runs Octopilot's dashboard with its Python deps (rich) without
  # touching the system Python. Installed only when missing: uv installed by
  # astral's script updates itself (`uv self update`).
  command -v uv &>/dev/null && return 0
  if [[ "$OS" == "Darwin" ]]; then
    brew install uv
  else
    sudo pacman -S --needed --noconfirm uv
  fi
}

# External modules: separate repos with their own install.sh. Each entry is
# "name|git-url|dir"; Octopilot's dir is where its checkout lives.
MODULES=(
  "octopilot|git@github.com:elboletaire/octopilot.git|${OCTOPILOT_DIR:-$HOME/src/octopilot}"
)

install_modules() {
  # Mode is install (clone when missing), update (also fast-forward) or relink
  # (run install.sh only when present, for ai-config, which installs nothing).
  local mode=${1:-install} entry name url dir
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name url dir <<< "$entry"
    install_module "$name" "$url" "$dir" "$mode"
  done
}

install_module() {
  # Never aborts the install: a module that fails only warns, and the rest runs.
  local name=$1 url=$2 dir=$3 mode=${4:-install}
  if [ ! -e "$dir" ]; then
    [ "$mode" = relink ] && return 0
    echo "Cloning $name into $dir"
    mkdir -p "$(dirname "$dir")"
    if ! git clone --quiet "$url" "$dir"; then
      echo "WARNING: could not clone $name from $url" >&2
      return 0
    fi
  elif [ "$mode" = update ]; then
    _pull_module "$name" "$dir"
  fi
  if [ -x "$dir/install.sh" ]; then
    "$dir/install.sh" || echo "WARNING: $name's install.sh failed (see above)" >&2
  fi
  return 0
}

_pull_module() {
  # Fast-forwards only a clean checkout on its default branch, so local work is
  # never touched. Offline or diverged just keeps the current checkout.
  local name=$1 dir=$2 branch default
  branch=$(git -C "$dir" symbolic-ref --short -q HEAD 2>/dev/null || true)
  default=$(git -C "$dir" symbolic-ref --short -q refs/remotes/origin/HEAD 2>/dev/null || true)
  default=${default#origin/}
  if [ -z "$branch" ] || [ "$branch" != "$default" ]; then
    echo "$name: not on its default branch; not updating it"
    return 0
  fi
  if [ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]; then
    echo "$name: uncommitted changes; not updating it"
    return 0
  fi
  git -C "$dir" pull --ff-only --quiet ||
    echo "$name: could not fast-forward (offline or diverged); keeping this checkout"
  return 0
}

link_herdr_plugin() {
  # The dotfiles' herdr plugins: Arxiu (genealogy board) and Taller (projects
  # board). Only linked when herdr is installed (install_herdr). Octopilot's
  # plugin is linked by its own install.sh.
  command -v herdr &>/dev/null || return 0
  # Plugin commands need a live server and exit 0 even when there is none.
  if herdr status server 2>/dev/null | grep -q "not running"; then
    echo "herdr server not running; skipping the herdr plugin links"
    return 0
  fi
  _link_herdr_plugin elboletaire.arxiu "$dotfiles/ai/arxiu/herdr"
  _link_herdr_plugin elboletaire.taller "$dotfiles/ai/taller/herdr"
}

link_herdr_app() {
  # Where dotfiles-owned herdr-app setup goes. Octopilot's mods are installed by
  # its own install.sh, run from install_modules.
  return 0
}

_herdr_plugin_root() {
  # Where the herdr plugin with this id is linked from; empty when it is not.
  herdr plugin list --json 2>/dev/null | python3 -c '
import json, sys
try:
    plugins = json.load(sys.stdin)["result"]["plugins"]
except Exception:
    plugins = []
print(next((p["plugin_root"] for p in plugins if p["plugin_id"] == sys.argv[1]), ""))
' "$1"
}

_link_herdr_plugin() {
  # Relinks when it points anywhere else (e.g. a worktree it was tested from).
  local id=$1 root=$2 current
  current=$(_herdr_plugin_root "$id")
  if [[ "$current" == "$root" ]]; then
    return 0
  fi
  if [[ -n "$current" ]]; then
    herdr plugin unlink "$id" >/dev/null || return 0
  fi
  if herdr plugin link "$root" >/dev/null; then
    echo "Linked herdr plugin $id -> $root"
  else
    echo "WARNING: could not link the herdr plugin (is a herdr server running?)" >&2
  fi
}

link_herdr_config() {
  # Tracked herdr config. An upgrade can replace the link with a plain file,
  # so rerun this after one.
  local src=$dotfiles/config/herdr/config.toml dest=~/.config/herdr/config.toml
  local backup
  mkdir -p "$(dirname "$dest")"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    return 0
  fi
  # Old symlink_config linked the whole dir: dest is then the tracked file itself.
  if [ "$dest" -ef "$src" ] && [ ! -L "$dest" ]; then
    echo "WARNING: $(dirname "$dest") is linked into the dotfiles; remove that link and rerun to use $dest" >&2
    return 0
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if cmp -s "$dest" "$src"; then
      rm "$dest"
    else
      backup=$oldfiles/config/herdr-config.toml.$(date +%Y%m%d%H%M%S)
      mkdir -p "$(dirname "$backup")"
      mv -v "$dest" "$backup"
      echo "WARNING: $dest was not the tracked link (a herdr upgrade does that); the old file is in $backup, merge anything new into $src" >&2
    fi
  fi
  ln -s "$src" "$dest" || return 1
  echo "Linked $dest -> $src"
  # A running server keeps the previous config until it is reloaded.
  if command -v herdr &>/dev/null && ! herdr status server 2>/dev/null | grep -q "not running"; then
    herdr server reload-config >/dev/null || echo "WARNING: could not reload the herdr config" >&2
  fi
}

merge_claude_settings() {
  # Merges the dotfiles-owned keys into ~/.claude/settings.json (other tools write
  # there too): our values win, the retired keys and hooks below are dropped, and
  # the file is rewritten only on change, with a backup.
  local src="$dotfiles/ai/claude/settings.json" dest="$HOME/.claude/settings.json"
  [ -f "$src" ] || return 0
  mkdir -p "$HOME/.claude"
  python3 - "$src" "$dest" <<'PY'
import json, os, re, shutil, sys

src, dest = sys.argv[1], os.path.realpath(sys.argv[2])
with open(src) as fh:
    base = json.load(fh)
try:
    with open(dest) as fh:
        cur = json.load(fh)
except FileNotFoundError:
    cur = {}
except (OSError, json.JSONDecodeError) as e:
    print(f"WARNING: {dest} is not valid JSON ({e}); left untouched", file=sys.stderr)
    sys.exit(0)


def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


# Keys these dotfiles used to write: the vocdoni marketplace and its plugin
# were replaced by APM. A parent left empty is removed.
RETIRED = [
    ("enabledPlugins", "vocdoni-contributing@vocdoni"),
    ("extraKnownMarketplaces", "vocdoni"),
]


def drop_retired(d):
    d = dict(d)
    for parent, key in RETIRED:
        if isinstance(d.get(parent), dict) and key in d[parent]:
            rest = {k: v for k, v in d[parent].items() if k != key}
            if rest:
                d[parent] = rest
            else:
                del d[parent]
    return d


# Hooks these dotfiles used to write: agent-deck and aoe hooks (any event) are
# gone. So is the old upstream contributing SessionStart hook: elboletaire/skills'
# contributing-rules hook injects the same rules, so keeping both injects them twice.
LEGACY_HOOK_MARKERS = ["agent-deck", "AOE_", "# aoe-hooks"]
# The old contributing hook, with $HOME or the expanded home directory.
LEGACY_CONTRIBUTING_HOOK = re.compile(
    r"""bash ["']?(\$HOME|~|[^"']*)/\.claude/hooks/contributing/hooks/session-start\.sh["']?"""
)


def is_legacy_hook(hook):
    cmd = str(hook.get("command", "")) if isinstance(hook, dict) else ""
    return bool(LEGACY_CONTRIBUTING_HOOK.fullmatch(cmd)) or any(m in cmd for m in LEGACY_HOOK_MARKERS)


def drop_legacy_hooks(d):
    hooks = d.get("hooks")
    if not isinstance(hooks, dict):
        return d
    out = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list):
                rest = [h for h in inner if not is_legacy_hook(h)]
                if not rest:
                    continue
                group = {**group, "hooks": rest}
            kept.append(group)
        # An event left empty by this removal goes too; one that was empty already stays.
        if kept or not groups:
            out[event] = kept
    return {**d, "hooks": out}


new = drop_legacy_hooks(drop_retired(merge(cur, base)))
if new == cur:
    sys.exit(0)
if os.path.exists(dest):
    shutil.copy2(dest, dest + ".dotfiles-bak")
mode = os.stat(dest).st_mode & 0o777 if os.path.exists(dest) else 0o600
tmp = f"{dest}.tmp.{os.getpid()}"
with open(tmp, "w") as fh:
    json.dump(new, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
os.chmod(tmp, mode)
os.replace(tmp, dest)
print(f"Merged dotfiles keys into {dest}")
PY
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
    if [ "$no_backup" -eq 1 ]; then
      rm -rf "$dest"
    else
      mkdir -p "$oldfiles"
      mv -v "$dest" "$oldfiles/"
    fi
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

  # Claude global instructions and subagent definitions.
  link_ai "$ai/claude/CLAUDE.md" ~/.claude/CLAUDE.md
  link_ai "$ai/claude/agents" ~/.claude/agents
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
    # curl, zsh, vim, and which are all pre-installed on macOS; vivid and jq
    # need Homebrew.
    if ! brew install vivid jq; then
      echo "Packages installation unsuccessful. ${aborting}" && exit 1
    fi
  else
    # Linux (Arch): use pacman
    if ! sudo pacman -Syu; then
      echo "Cannot update pacman. ${aborting}" && exit 1
    fi
    # Install common required packages. We don't install git, as it's the way to
    # install the dotfiles. base-devel is needed to build AUR packages below.
    if ! sudo pacman -S --needed --noconfirm base-devel curl zsh vivid vim which jq; then
      echo "Packages installation unsuccessful. ${aborting}" && exit 1
    fi
    # yay is an AUR helper, and the AUR is not an official repo, so pacman
    # cannot install it: bootstrap it with makepkg the first time around.
    if ! command -v yay &>/dev/null; then
      local yay_src
      yay_src="$(mktemp -d)"
      if ! git clone --depth 1 https://aur.archlinux.org/yay-bin.git "$yay_src" ||
        ! (cd "$yay_src" && makepkg -si --noconfirm); then
        rm -rf "$yay_src"
        echo "Could not bootstrap yay. ${aborting}" && exit 1
      fi
      rm -rf "$yay_src"
    fi
    if ! yay -S --needed --noconfirm obscura-browser-bin; then
      echo "Could not install AUR packages. ${aborting}" && exit 1
    fi
  fi
}

set_login_shell() {
  # chsh asks for a password, so only run it when the account's login shell
  # (not $SHELL, which can be stale) isn't zsh yet. Compared by name, since
  # /bin/zsh and /usr/bin/zsh are the same shell.
  local zsh current
  zsh=$(command -v zsh) || return 0
  if [[ "$OS" == "Darwin" ]]; then
    current=$(dscl . -read ~/ UserShell 2>/dev/null | awk '{ print $2 }')
  else
    current=$(getent passwd "$USER" | cut -d: -f7)
  fi
  [[ "${current##*/}" == zsh ]] && return 0
  chsh -s "$zsh"
}

do_install() {
  cleanup_legacy
  install_packages
  install_nvm               # must come before anything that needs node/npx/npm
  install_ai_agents         # claude-code and pi need node from the step above
  install_apm || return 1   # apm manages skills
  install_herdr             # after install_ai_agents: wires agent-state hooks
  install_herdr_app         # the herdr desktop app; also installs herdr-core if missing
  install_uv
  git submodule update --init --recursive
  symlink
  symlink_config
  install_rtk               # wires hooks into claude and pi, which must exist first
  symlink_ai || return 1    # config symlinks
  install_skills || return 1
  merge_claude_settings
  link_herdr_config
  install_modules
  link_herdr_plugin
  link_herdr_app
  set_login_shell
  vim -c 'PluginInstall' -c 'qa!'
  echo "dotfiles installation was successful"
}

do_update() {
  # Lightweight: no system packages, no submodule version bump.
  cleanup_legacy
  git submodule update --init --recursive
  install_nvm
  install_ai_agents
  install_apm || return 1
  install_herdr update
  install_herdr_app update
  install_uv
  symlink
  symlink_config
  install_rtk update
  symlink_ai || return 1
  install_skills || return 1
  merge_claude_settings
  link_herdr_config
  install_modules update
  link_herdr_plugin
  link_herdr_app
  echo "dotfiles update complete"
}

do_update_ai() {
  # AI-only fast path: refresh rtk, its hooks, the AI symlinks and the skills.
  cleanup_legacy
  install_nvm
  install_ai_agents
  install_apm || return 1
  install_herdr update
  install_herdr_app update
  install_uv
  install_rtk update
  symlink_ai || return 1
  install_skills || return 1
  merge_claude_settings
  link_herdr_config
  install_modules update
  link_herdr_plugin
  link_herdr_app
  echo "AI stack update complete"
}

do_install_ai_config() {
  # Config-only: relink prompts, instructions and agents from ai/ and install
  # the pinned skills. No agents, node or tooling installs, no ref bumps, and
  # no ~/old_dotfiles backups since everything relinked is tracked in git.
  no_backup=1
  cleanup_legacy
  symlink_ai || return 1
  install_skills || return 1
  merge_claude_settings
  install_modules relink
  link_herdr_plugin
  link_herdr_app
  echo "AI config install complete"
}

do_skills_bump() {
  # Moves every skill to the latest commit of its ref: the only path that does.
  install_apm || return 1
  skills_bump
}

do_herdr() {
  # Repairs herdr's setup without upgrading herdr or herdr-app: config and plugin links.
  install_herdr
  link_herdr_config
  install_modules
  link_herdr_plugin
  link_herdr_app
  echo "herdr setup complete"
}

# Library guard: when sourced (e.g. from tests), stop here.
# The case block only runs when executed directly.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  return 0 2>/dev/null || true
fi

case "${1:-install}" in
  install) do_install || exit 1 ;;
  update)  do_update || exit 1 ;;
  ai)      do_update_ai || exit 1 ;;
  ai-config) do_install_ai_config || exit 1 ;;
  herdr)   do_herdr || exit 1 ;;
  skills-bump) do_skills_bump || exit 1 ;;
  *) echo "usage: $(basename "$0") [install|update|ai|ai-config|herdr|skills-bump]" && exit 1 ;;
esac
