#!/bin/bash
# Uninstaller for Claude Code WebUI hooks (new architecture)
#
# Reverses what install.sh does: removes hook configuration from settings.json
# and (for global scope) removes symlinks from ~/.claude/hooks/.
# Also cleans up old .sh symlinks from the previous architecture.
#
# Scopes:
#   --project  Remove hooks from <cwd>/.claude/settings.json
#   --global   Remove hooks from ~/.claude/settings.json + remove symlinks from ~/.claude/hooks/
#   --daemon   Remove systemd service (Linux only)
#
# Usage: /path/to/uninstall.sh --project|--global|--daemon [--daemon]
# Deps:  jq

set -e

PROJECT_DIR="$(pwd)"
HOOKS_DIR="$HOME/.claude/hooks"

usage() {
  echo "Usage: $0 --project|--global|--daemon [--daemon]"
  echo ""
  echo "  --project  Remove hooks from <cwd>/.claude/settings.json"
  echo "  --global   Remove hooks from ~/.claude/settings.json + symlinks"
  echo "  --daemon   Remove systemd service (Linux only)"
  echo ""
  echo "Flags can be combined: $0 --global --daemon"
  exit 1
}

prompt_scope() {
  echo "Select uninstall scope:"
  echo "  1) project  — Remove hooks from <cwd>/.claude/settings.json"
  echo "  2) global   — Remove hooks from ~/.claude/settings.json + symlinks"
  echo "  3) daemon   — Remove systemd service (Linux only)"
  echo ""
  echo "Enter choices separated by space (e.g. '1 3' or '2'):"
  printf "> "
  read -r choices
  for c in $choices; do
    case "$c" in
      1) DO_PROJECT=true ;;
      2) DO_GLOBAL=true ;;
      3) DO_DAEMON=true ;;
      *) echo "Invalid choice: $c"; exit 1 ;;
    esac
  done
  if [ "$DO_PROJECT" = false ] && [ "$DO_GLOBAL" = false ] && [ "$DO_DAEMON" = false ]; then
    echo "No scope selected"; exit 1
  fi
}

DO_PROJECT=false
DO_GLOBAL=false
DO_DAEMON=false

if [ $# -eq 0 ]; then
  prompt_scope
else
  for arg in "$@"; do
    case "$arg" in
      --project) DO_PROJECT=true ;;
      --global)  DO_GLOBAL=true ;;
      --daemon)  DO_DAEMON=true ;;
      *)         usage ;;
    esac
  done
fi

remove_hooks_from_settings() {
  local settings_file="$1"

  if [ ! -f "$settings_file" ]; then
    echo "No settings file found: $settings_file (skipping)"
    return
  fi

  local updated
  updated=$(jq 'del(.hooks)' "$settings_file")

  if [ "$updated" = "{}" ]; then
    rm -f "$settings_file"
    echo "Removed empty: $settings_file"

    # Remove .claude/ dir if empty (only for project-level)
    local settings_dir
    settings_dir="$(dirname "$settings_file")"
    if [ -d "$settings_dir" ] && [ -z "$(ls -A "$settings_dir")" ]; then
      rmdir "$settings_dir"
      echo "Removed empty directory: $settings_dir"
    fi
  else
    echo "$updated" > "$settings_file"
    echo "Removed hooks from: $settings_file"
  fi
}

remove_symlinks() {
  local removed=0
  # Remove new .py symlinks
  for script in hook-permission-request.py hook-session-start.py hook-session-end.py; do
    if [ -L "$HOOKS_DIR/$script" ]; then
      rm -f "$HOOKS_DIR/$script"
      removed=$((removed + 1))
    fi
  done
  # Also clean up old symlinks from previous architectures
  for script in permission-request.py session-start.py session-end.py permission-request.sh post-tool-use.sh stop.sh user-prompt-submit.sh session-start.sh session-end.sh; do
    if [ -L "$HOOKS_DIR/$script" ]; then
      rm -f "$HOOKS_DIR/$script"
      removed=$((removed + 1))
    fi
  done
  echo "Removed $removed symlinks from: $HOOKS_DIR"
}

uninstall_daemon() {
  if [ "$(uname)" != "Linux" ]; then
    echo "WARNING: --daemon is Linux only (systemd). Skipping on $(uname)."
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl not found, skipping daemon removal."
    return
  fi
  sudo systemctl disable --now claude-webui.service claude-webui-watcher.service 2>/dev/null || true
  sudo rm -f /etc/systemd/system/claude-webui.service /etc/systemd/system/claude-webui-watcher.service
  sudo systemctl daemon-reload
  echo "Daemon services removed"
}

if [ "$DO_DAEMON" = true ]; then
  uninstall_daemon
fi

if [ "$DO_GLOBAL" = true ]; then
  remove_symlinks
  remove_hooks_from_settings "$HOME/.claude/settings.json"
  echo "WebUI hooks uninstalled globally"
fi

if [ "$DO_PROJECT" = true ]; then
  remove_hooks_from_settings "$PROJECT_DIR/.claude/settings.json"
  echo "WebUI hooks uninstalled for: $PROJECT_DIR"
fi
