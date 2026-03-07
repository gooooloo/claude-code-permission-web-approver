#!/usr/bin/env python3
"""
SessionStart hook for Claude Code WebUI (new architecture).

Called on session lifecycle events: startup, resume, /clear, /compact.
Registers this session with the server, passing transcript path, tmux info, and cwd.

Input:  JSON on stdin with { source: "startup"|"resume"|"clear"|"compact" }
Output: (none)
"""

import json
import os
import sys
import glob
import urllib.request

SERVER = "http://127.0.0.1:19836"
QUEUE_DIR = "/tmp/claude-webui"


def find_transcript_path():
    """Find the most recently modified transcript JSONL for this project."""
    project_dir = os.getcwd()
    # Claude Code encodes project path: /home/user/project -> -home-user-project
    encoded = project_dir.replace("/", "-")
    if not encoded.startswith("-"):
        encoded = "-" + encoded
    projects_dir = os.path.join(os.path.expanduser("~"), ".claude", "projects", encoded)
    if not os.path.isdir(projects_dir):
        return ""
    jsonl_files = glob.glob(os.path.join(projects_dir, "*.jsonl"))
    if not jsonl_files:
        return ""
    # Return the most recently modified
    return max(jsonl_files, key=os.path.getmtime)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    source = input_data.get("source", "unknown")
    session_id = str(os.getppid())
    project_dir = os.getcwd()
    transcript_path = find_transcript_path()
    tmux_pane = os.environ.get("TMUX_PANE", "")
    tmux_socket = os.environ.get("TMUX", "")

    body = json.dumps({
        "session_id": session_id,
        "source": source,
        "transcript_path": transcript_path,
        "tmux_pane": tmux_pane,
        "tmux_socket": tmux_socket,
        "cwd": project_dir,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{SERVER}/api/session/register",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass  # Fire-and-forget; server may be offline


if __name__ == "__main__":
    main()
