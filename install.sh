#!/bin/bash
# Installer for Claude Code WebUI hooks (new architecture)
#
# Installs 3 Python hook scripts (PermissionRequest, SessionStart, SessionEnd).
# No external dependencies (no jq, curl — hooks are pure Python).
#
# Scopes:
#   --project  Install hooks into <cwd>/.claude/settings.json (project-level only)
#   --global   Install hooks into ~/.claude/settings.json + create symlinks in ~/.claude/hooks/
#   --daemon   Install systemd service for auto-start (Linux only)
#
# Usage: /path/to/install.sh --project|--global|--daemon [--daemon]
# Deps:  jq (for settings.json manipulation only)

set -e

SHARED_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(pwd)"
HOOKS_DIR="$HOME/.claude/hooks"

usage() {
  echo "Usage: $0 --project|--global|--daemon [--daemon]"
  echo ""
  echo "  --project  Install hooks into <cwd>/.claude/settings.json"
  echo "  --global   Install hooks into ~/.claude/settings.json + symlinks"
  echo "  --daemon   Install systemd service for auto-start (Linux only)"
  echo ""
  echo "Flags can be combined: $0 --global --daemon"
  exit 1
}

prompt_scope() {
  echo "Select install scope:"
  echo "  1) project  — Install hooks into <cwd>/.claude/settings.json"
  echo "  2) global   — Install hooks into ~/.claude/settings.json + symlinks"
  echo "  3) daemon   — Install systemd service for auto-start (Linux only)"
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

# Resolve $HOME at install time — Claude Code may not use a shell that expands env vars
HOOKS_PATH="$HOME/.claude/hooks"
HOOKS_CONFIG="$(cat <<EOFJSON
{
  "PermissionRequest": [
    {
      "matcher": ".*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$HOOKS_PATH/hook-permission-request.py\"",
          "timeout": 86400
        }
      ]
    }
  ],
  "SessionStart": [
    {
      "matcher": ".*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$HOOKS_PATH/hook-session-start.py\"",
          "timeout": 5
        }
      ]
    }
  ],
  "SessionEnd": [
    {
      "matcher": ".*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$HOOKS_PATH/hook-session-end.py\"",
          "timeout": 5
        }
      ]
    }
  ]
}
EOFJSON
)"

install_symlinks() {
  mkdir -p "$HOOKS_DIR"
  # Also remove old symlinks from previous architectures
  for old_script in permission-request.py session-start.py session-end.py permission-request.sh post-tool-use.sh stop.sh user-prompt-submit.sh session-start.sh session-end.sh; do
    [ -L "$HOOKS_DIR/$old_script" ] && rm -f "$HOOKS_DIR/$old_script"
  done
  for script in hook-permission-request.py hook-session-start.py hook-session-end.py; do
    ln -sf "$SHARED_DIR/$script" "$HOOKS_DIR/$script"
  done
  echo "Symlinked hooks to: $HOOKS_DIR"
}

install_settings() {
  local settings_file="$1"
  local settings_dir
  settings_dir="$(dirname "$settings_file")"

  mkdir -p "$settings_dir"

  if [ -f "$settings_file" ]; then
    EXISTING=$(cat "$settings_file")
    echo "$EXISTING" | jq --argjson hooks "$HOOKS_CONFIG" '.hooks = $hooks' > "$settings_file.tmp" && mv "$settings_file.tmp" "$settings_file"
    echo "Updated: $settings_file"
  else
    echo "$HOOKS_CONFIG" | jq '{hooks: .}' > "$settings_file"
    echo "Created: $settings_file"
  fi
}

install_daemon() {
  if [ "$(uname)" != "Linux" ]; then
    echo "WARNING: --daemon is Linux only (systemd). Skipping on $(uname)."
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemctl not found. Is systemd installed?"
    exit 1
  fi
  if ! command -v inotifywait >/dev/null 2>&1; then
    echo "Installing inotify-tools..."
    sudo apt install -y inotify-tools
  fi
  sudo cp "$SHARED_DIR/claude-webui-linux.service" /etc/systemd/system/claude-webui.service
  sudo cp "$SHARED_DIR/claude-webui-watcher-linux.service" /etc/systemd/system/claude-webui-watcher.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now claude-webui.service claude-webui-watcher.service
  echo "Daemon installed and started (claude-webui + claude-webui-watcher)"
}

if [ "$DO_GLOBAL" = true ]; then
  install_symlinks
  install_settings "$HOME/.claude/settings.json"
  echo "WebUI hooks installed globally (all projects)"
fi

if [ "$DO_PROJECT" = true ]; then
  # Symlinks are always needed — hook commands reference $HOME/.claude/hooks/
  install_symlinks
  install_settings "$PROJECT_DIR/.claude/settings.json"
  echo "WebUI hooks installed for: $PROJECT_DIR"
fi

if [ "$DO_DAEMON" = true ]; then
  install_daemon
fi

echo "Start the server: python3 $SHARED_DIR/server.py"
echo "Then open: http://localhost:19836"
