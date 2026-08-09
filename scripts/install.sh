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

install_apm() {
  # APM (Agent Package Manager): skill & primitive manager for AI agents.
  # https://github.com/microsoft/apm
  if command -v apm &>/dev/null; then
    echo "apm already installed ($(apm --version 2>/dev/null || echo present))"
    return
  fi
  if [[ "$OS" == "Darwin" ]]; then
    brew install microsoft/apm/apm
  else
    local tmp_installer
    tmp_installer="$(mktemp)"
    if ! curl -fsSL https://aka.ms/apm-unix -o "$tmp_installer"; then
      echo "ERROR: Failed to download APM installer" >&2
      rm -f "$tmp_installer"
      return 1
    fi
    bash "$tmp_installer"
    local install_rc=$?
    rm -f "$tmp_installer"
    return $install_rc
  fi
}

install_aoe() {
  # aoe (Agent of Empires): tmux-based session manager for AI coding agents.
  # https://github.com/agent-of-empires/agent-of-empires
  # Pass "update" to force an upgrade even when aoe is already installed.
  local mode=$1
  local installer="https://raw.githubusercontent.com/agent-of-empires/agent-of-empires/main/scripts/install.sh"

  if [[ "$mode" == "update" ]]; then
    if [[ "$OS" == "Darwin" ]]; then
      brew upgrade aoe || brew install aoe
    else
      curl -fsSL "$installer" | bash
    fi
  elif command -v aoe &>/dev/null; then
    echo "aoe already installed ($(aoe --version 2>/dev/null || echo present))"
  elif [[ "$OS" == "Darwin" ]]; then
    brew install aoe
  else
    curl -fsSL "$installer" | bash
  fi
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

# Derive tracked skill names from the project lockfile.
# Outputs one skill name per line.
_tracked_skill_names() {
  local lockfile=$1
  # Extract "name:" fields from lockfile dependencies section.
  sed -n '/^dependencies:/,/^[a-z]/p' "$lockfile" \
    | grep '^[[:space:]]*name:' \
    | sed 's/.*name:[[:space:]]*//; s/[[:space:]]*$//' \
    | sort -u
}

# Remove legacy per-skill symlinks that point into ~/.agents/skills and are
# owned by the tracked dotfiles APM lockfile. Preserves foreign symlinks,
# regular directories, and regular files.
#
# Ownership is derived from the tracked ai/apm.lock.yaml: only symlinks whose
# basename matches a skill name listed in the lock AND whose resolved target
# falls under ~/.agents/skills are removed. Dangling managed symlinks are
# handled without requiring the target to exist.
clean_legacy_skill_symlinks() {
  local lockfile=$1   # path to the tracked ai/apm.lock.yaml
  local rollback_file=${2:-}  # optional: if set, record removed path<TAB>target
  local agents_skills="$HOME/.agents/skills"
  local dir

  if [ ! -f "$lockfile" ] || [ ! -r "$lockfile" ]; then
    echo "Warning: cannot read lockfile $lockfile; skipping legacy cleanup"
    return 0
  fi

  # Collect tracked skill names into a fast lookup
  local tracked
  tracked=$(_tracked_skill_names "$lockfile")

  for dir in "$HOME/.pi/agent/skills" "$HOME/.claude/skills"; do
    if [ ! -d "$dir" ]; then
      continue
    fi
    local link
    for link in "$dir"/*; do
      # Skip if glob didn't expand
      [ -e "$link" ] || [ -L "$link" ] || continue
      # Skip non-symlinks
      if [ ! -L "$link" ]; then
        continue
      fi
      local basename
      basename="$(basename "$link")"

      # Only remove symlinks whose basename is a tracked skill name
      if ! echo "$tracked" | grep -qxF "$basename"; then
        continue
      fi

      # Resolve target; handle dangling symlinks by using readlink directly
      local target
      target="$(readlink "$link")"
      # Resolve relative links against the link's directory
      local resolved
      if [[ "$target" == /* ]]; then
        resolved="$target"
      else
        resolved="$(cd "$(dirname "$link")" && cd "$(dirname "$target")" 2>/dev/null && pwd)/$(basename "$target")" || true
      fi

      # Remove if the resolved target is under ~/.agents/skills (or dangling
      # whose readlink suggests it was meant to point there)
      if [[ "$target" == "$agents_skills"/* ]] || [[ "$resolved" == "$agents_skills"/* ]]; then
        echo "Removing legacy symlink: $link -> $target"
        # Record removal before deleting, for potential rollback
        if [ -n "$rollback_file" ]; then
          printf '%s\t%s\n' "$link" "$target" >> "$rollback_file"
        fi
        rm "$link"
      fi
    done
  done
}

_global_apm_has_dotfiles_package() {
  local ai=$dotfiles/ai
  local manifest=$HOME/.apm/apm.yml
  [ -f "$manifest" ] || return 1

  awk -v needle="$ai" '
    /^[[:space:]]*-[[:space:]]*/ {
      value = $0
      sub(/^[[:space:]]*-[[:space:]]*/, "", value)
      if (value == needle) found = 1
    }
    END { exit(found ? 0 : 1) }
  ' "$manifest"
}

_dotfiles_retired_skill_names() {
  local global_lock=$1
  local current_lock=$2
  local ai=$dotfiles/ai
  [ -r "$global_lock" ] || return 0

  local resolver current_names
  resolver=$(awk -v needle="$ai" '
    /^-[[:space:]]repo_url:/ {
      repo = $0
      sub(/^-[[:space:]]repo_url:[[:space:]]*/, "", repo)
    }
    /^[[:space:]]+local_path:/ {
      path = $0
      sub(/^[[:space:]]+local_path:[[:space:]]*/, "", path)
      if (path == needle) { print repo; exit }
    }
  ' "$global_lock")
  [ -n "$resolver" ] || return 0

  current_names=$(_tracked_skill_names "$current_lock")
  awk -v owner="$resolver" '
    function emit() {
      if (name != "" && resolved_by == owner) print name
    }
    /^-[[:space:]]repo_url:/ {
      emit()
      name = ""
      resolved_by = ""
      next
    }
    /^[[:space:]]+name:/ {
      name = $0
      sub(/^[[:space:]]+name:[[:space:]]*/, "", name)
      next
    }
    /^[[:space:]]+resolved_by:/ {
      resolved_by = $0
      sub(/^[[:space:]]+resolved_by:[[:space:]]*/, "", resolved_by)
    }
    END { emit() }
  ' "$global_lock" | sort -u | while IFS= read -r name; do
    if ! printf '%s\n' "$current_names" | grep -qxF "$name"; then
      printf '%s\n' "$name"
    fi
  done
}

_remove_retired_skill_dirs() {
  local retired_file=$1
  [ -s "$retired_file" ] || return 0

  local name root path
  while IFS= read -r name; do
    # Refuse malformed names so a lockfile value can never escape a skill root.
    if [[ ! "$name" =~ ^[A-Za-z0-9._-]+$ ]]; then
      echo "Warning: refusing unsafe retired skill name: $name" >&2
      continue
    fi
    for root in "$HOME/.agents/skills" "$HOME/.claude/skills"; do
      path="$root/$name"
      # Only remove directories previously owned by this APM package. Preserve
      # regular files and symlinks at the same path as potentially foreign.
      if [ -d "$path" ] && [ ! -L "$path" ]; then
        rm -rf "$path"
        echo "Removed retired dotfiles skill: $path"
      fi
    done
  done < "$retired_file"
}

_restore_legacy_skill_symlinks() {
  local rollback_file=$1
  [ -s "$rollback_file" ] || return 0

  local link_path target
  while IFS=$'\t' read -r link_path target; do
    if [ ! -e "$link_path" ] && [ ! -L "$link_path" ]; then
      ln -s "$target" "$link_path"
      echo "Restored: $link_path -> $target"
    fi
  done < "$rollback_file"
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

  # Skills: managed by APM (Agent Package Manager).
  # Treat the ai/ directory as a local APM package. A global install reads the
  # package's apm.yml + apm.lock.yaml and adds its dependencies to ~/.apm/
  # without overwriting unrelated global entries.
  if command -v apm &>/dev/null; then
    local rollback_file validation_root retired_file="" global_lock_backup=""
    local global_manifest_backup=""
    local replace_existing=0

    # APM replays the flattened global lock for an unchanged local package path;
    # it does not notice removed transitive skills. Validate the new graph first,
    # then rebuild the global lock so unrelated direct dependencies are preserved
    # while this local package's changed transitive graph is re-resolved.
    if _global_apm_has_dotfiles_package; then
      replace_existing=1
      validation_root="$(mktemp -d)" || return 1
      echo "Validating the updated dotfiles skill graph..."
      if ! (cd "$ai" && apm install --frozen --root "$validation_root" --target agent-skills,claude); then
        echo "ERROR: updated dotfiles skill graph failed validation" >&2
        rm -rf "$validation_root"
        return 1
      fi
      rm -rf "$validation_root"

      retired_file="$(mktemp)" || return 1
      if ! _dotfiles_retired_skill_names "$HOME/.apm/apm.lock.yaml" \
        "$ai/apm.lock.yaml" > "$retired_file"; then
        rm -f "$retired_file"
        return 1
      fi

      global_manifest_backup="$(mktemp)" || { rm -f "$retired_file"; return 1; }
      cp "$HOME/.apm/apm.yml" "$global_manifest_backup" || {
        rm -f "$retired_file" "$global_manifest_backup"
        return 1
      }
      if [ -f "$HOME/.apm/apm.lock.yaml" ]; then
        global_lock_backup="$(mktemp)" || {
          rm -f "$retired_file" "$global_manifest_backup"
          return 1
        }
        cp "$HOME/.apm/apm.lock.yaml" "$global_lock_backup" || {
          rm -f "$retired_file" "$global_manifest_backup" "$global_lock_backup"
          return 1
        }
      fi
    fi

    rollback_file="$(mktemp)" || {
      rm -f "$retired_file" "$global_manifest_backup" "$global_lock_backup"
      return 1
    }

    # Clean legacy symlinks before installing, recording removals for rollback.
    # Ownership is derived from the tracked lockfile.
    clean_legacy_skill_symlinks "$ai/apm.lock.yaml" "$rollback_file"

    if [ "$replace_existing" -eq 1 ]; then
      echo "Removing the cached dotfiles APM package graph..."
      if ! apm uninstall -g "$ai"; then
        echo "ERROR: apm uninstall -g failed; restoring global APM state" >&2
        _restore_legacy_skill_symlinks "$rollback_file"
        cp "$global_manifest_backup" "$HOME/.apm/apm.yml"
        if [ -n "$global_lock_backup" ]; then
          cp "$global_lock_backup" "$HOME/.apm/apm.lock.yaml"
        fi
        rm -f "$rollback_file" "$retired_file" "$global_manifest_backup" "$global_lock_backup"
        return 1
      fi
      echo "Rebuilding the global APM dependency graph..."
      rm -f "$HOME/.apm/apm.lock.yaml"
    fi

    # Install the local package globally. APM reads ai/apm.yml + ai/apm.lock.yaml
    # and deploys skills. APM v0.28.0 supports comma-separated multi-target.
    echo "Installing dotfiles skills via APM..."
    if ! apm install -g "$ai" --target agent-skills,claude; then
      echo "ERROR: apm install -g failed" >&2
      _restore_legacy_skill_symlinks "$rollback_file"
      if [ -n "$global_manifest_backup" ]; then
        cp "$global_manifest_backup" "$HOME/.apm/apm.yml"
      fi
      if [ -n "$global_lock_backup" ]; then
        cp "$global_lock_backup" "$HOME/.apm/apm.lock.yaml"
      fi
      rm -f "$rollback_file" "$retired_file" "$global_manifest_backup" "$global_lock_backup"
      return 1
    fi

    _remove_retired_skill_dirs "$retired_file"
    if [ "$replace_existing" -eq 1 ]; then
      if ! (cd "$HOME/.apm" && apm prune); then
        echo "Warning: APM could not prune orphaned package cache entries" >&2
      fi
    fi
    rm -f "$rollback_file" "$retired_file" "$global_manifest_backup" "$global_lock_backup"

    # Remove legacy .skill-lock.json symlink only after a successful APM install,
    # and only when it is a symlink (preserve foreign regular files).
    local lock_link="$HOME/.agents/.skill-lock.json"
    if [ -L "$lock_link" ]; then
      echo "Removing legacy skill lock symlink: $lock_link"
      rm "$lock_link"
    fi
  else
    echo "apm not found; skipping skills install."
    echo "Install APM, then re-run: bash $dotfiles/scripts/install.sh"
  fi
}

# Refresh each pinned dependency to the HEAD commit of its configured Git URL.
# APM cannot update arbitrary SHA pins when upstreams lack compatible annotated
# semver tags, so resolve default-branch commits first and let APM validate and
# lock the resulting exact refs.
_refresh_apm_refs() {
  local manifest=$1
  local cache_file=$2
  local output_file="$manifest.next"
  local current_git=""
  local line refs commit indent

  : > "$output_file" || return 1
  : > "$cache_file" || { rm -f "$output_file"; return 1; }

  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^[[:space:]]*-[[:space:]]git:[[:space:]](.+)$ ]]; then
      current_git="${BASH_REMATCH[1]}"
      current_git="${current_git%$'\r'}"
      printf '%s\n' "$line" >> "$output_file" || return 1
      continue
    fi

    if [[ "$line" =~ ^([[:space:]]*)ref:[[:space:]].*$ ]]; then
      indent="${BASH_REMATCH[1]}"
      if [ -z "$current_git" ]; then
        echo "ERROR: ref entry has no preceding git URL in $manifest" >&2
        rm -f "$output_file"
        return 1
      fi

      commit=$(awk -F '\t' -v url="$current_git" '$1 == url { print $2; exit }' "$cache_file")
      if [ -z "$commit" ]; then
        if ! refs=$(git ls-remote "$current_git" HEAD); then
          echo "ERROR: could not resolve HEAD for $current_git" >&2
          rm -f "$output_file"
          return 1
        fi
        commit=$(printf '%s\n' "$refs" | awk 'NR == 1 { print $1 }')
        if [ "${#commit}" -ne 40 ] || [[ "$commit" == *[!0-9a-fA-F]* ]]; then
          echo "ERROR: invalid HEAD commit for $current_git: $commit" >&2
          rm -f "$output_file"
          return 1
        fi
        printf '%s\t%s\n' "$current_git" "$commit" >> "$cache_file" || return 1
      fi

      printf '%sref: %s\n' "$indent" "$commit" >> "$output_file" || return 1
      continue
    fi

    printf '%s\n' "$line" >> "$output_file" || return 1
  done < "$manifest"

  mv "$output_file" "$manifest"
}

update_apm_skills() {
  # Refresh upstream default-branch commits in an isolated project, then let
  # APM validate the exact pins and rebuild the tracked lockfile. Nothing is
  # copied back unless every ref resolves and the project install succeeds.
  if ! command -v apm &>/dev/null; then
    echo "apm not found; skipping skills update."
    return 1
  fi

  local ai=$dotfiles/ai
  local tmpdir
  tmpdir="$(mktemp -d)" || return 1

  cp "$ai/apm.yml" "$tmpdir/apm.yml" || { rm -rf "$tmpdir"; return 1; }
  cp "$ai/apm.lock.yaml" "$tmpdir/apm.lock.yaml" || { rm -rf "$tmpdir"; return 1; }

  echo "Resolving latest skill commits..."
  if ! _refresh_apm_refs "$tmpdir/apm.yml" "$tmpdir/ref-cache"; then
    echo "ERROR: failed to refresh skill refs; tracked ai/ files unchanged." >&2
    rm -rf "$tmpdir"
    return 1
  fi

  rm -f "$tmpdir/apm.lock.yaml"
  if ! (cd "$tmpdir" && apm install --target agent-skills,claude); then
    echo "ERROR: APM validation failed; tracked ai/ files unchanged." >&2
    rm -rf "$tmpdir"
    return 1
  fi
  if [ ! -f "$tmpdir/apm.lock.yaml" ]; then
    echo "ERROR: APM did not generate apm.lock.yaml; tracked ai/ files unchanged." >&2
    rm -rf "$tmpdir"
    return 1
  fi

  # Stage both outputs before replacing either tracked file. Keep same-filesystem
  # backups so a failed second swap can restore the original matched pair.
  local transaction_id manifest_stage lock_stage manifest_backup lock_backup
  transaction_id="$(basename "$tmpdir")"
  manifest_stage="$ai/.apm.yml.$transaction_id.new"
  lock_stage="$ai/.apm.lock.yaml.$transaction_id.new"
  manifest_backup="$ai/.apm.yml.$transaction_id.backup"
  lock_backup="$ai/.apm.lock.yaml.$transaction_id.backup"

  if ! cp "$tmpdir/apm.yml" "$manifest_stage" || \
     ! cp "$tmpdir/apm.lock.yaml" "$lock_stage" || \
     ! cp "$ai/apm.yml" "$manifest_backup" || \
     ! cp "$ai/apm.lock.yaml" "$lock_backup"; then
    echo "ERROR: could not stage updated APM state; tracked ai/ files unchanged." >&2
    rm -f "$manifest_stage" "$lock_stage" "$manifest_backup" "$lock_backup"
    rm -rf "$tmpdir"
    return 1
  fi

  if ! mv "$manifest_stage" "$ai/apm.yml"; then
    echo "ERROR: could not replace ai/apm.yml; tracked ai/ files unchanged." >&2
    rm -f "$manifest_stage" "$lock_stage" "$manifest_backup" "$lock_backup"
    rm -rf "$tmpdir"
    return 1
  fi
  if ! mv "$lock_stage" "$ai/apm.lock.yaml"; then
    echo "ERROR: could not replace ai/apm.lock.yaml; restoring original pair." >&2
    mv -f "$manifest_backup" "$ai/apm.yml"
    mv -f "$lock_backup" "$ai/apm.lock.yaml"
    rm -f "$manifest_stage" "$lock_stage" "$manifest_backup" "$lock_backup"
    rm -rf "$tmpdir"
    return 1
  fi

  rm -f "$manifest_backup" "$lock_backup"
  rm -rf "$tmpdir"
  echo "Skill refs and apm.lock.yaml updated in the repo. Review & commit the bump."
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
  install_nvm               # must come before anything that needs node/npx/npm
  install_ai_agents         # claude-code and pi need node from the step above
  install_apm || return 1   # apm manages skills
  install_aoe
  git submodule update --init --recursive
  symlink
  symlink_config
  install_rtk               # wires hooks into claude and pi, which must exist first
  symlink_ai || return 1    # config symlinks + APM skills global install
  chsh -s "$(which zsh)"
  vim -c 'PluginInstall' -c 'qa!'
  echo "dotfiles installation was successful"
}

do_update() {
  # Lightweight: no system packages, no submodule version bump.
  git submodule update --init --recursive
  install_nvm
  install_ai_agents
  install_apm || return 1
  install_aoe update
  symlink
  symlink_config
  install_rtk update
  update_apm_skills || return 1
  symlink_ai || return 1
  echo "dotfiles update complete"
}

do_update_ai() {
  # AI-only fast path: refresh rtk, its hooks, the AI symlinks and the skills.
  install_nvm
  install_ai_agents
  install_apm || return 1
  install_aoe update
  install_rtk update
  update_apm_skills || return 1
  symlink_ai || return 1
  echo "AI stack update complete"
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
  *) echo "usage: $(basename "$0") [install|update|ai]" && exit 1 ;;
esac
