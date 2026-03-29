#!/usr/bin/env python3
"""
PermissionRequest hook for Claude Code WebUI.

Called before Claude executes a tool that requires permission.

Auto-allow tiers (checked in order, first match wins):
  1. WebUI rules        — 4-level rule engine (repo/user/project levels, checked locally)
  2. Tmux allowlist     — tmux commands used by WebUI prompt delivery
  3. Session rules      — per-session rules stored in server memory, queried via API
  4. Server offline     — if the server is unreachable, auto-allow everything

If none match, the hook writes a .request.json and polls for a .response.json.

Input:  JSON on stdin with { tool_name, tool_input }
Output: JSON on stdout with { hookSpecificOutput: { decision: { behavior: "allow"|"deny" } } }
"""

import atexit
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid

from platform_utils import get_queue_dir, find_claude_pid
import permission_rules

QUEUE_DIR = get_queue_dir()
SERVER = "http://127.0.0.1:19836"
TIMEOUT = 86400  # 24 hours


def allow_response():
    """Output an allow decision and exit."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"}
        }
    }))
    sys.exit(0)


def deny_response(message="User denied via web UI"):
    """Output a deny decision and exit."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": message}
        }
    }))
    sys.exit(0)


def build_detail(tool_name, tool_input):
    """Build detail text, detail_sub, allow_rule, and allow_rules per tool type.

    allow_rule: a single rule dict for "Always Allow" (e.g. {"tool": "Bash", "prefix": "git commit", "action": "allow"})
    allow_rules: list of rule dicts for compound Bash commands
    """
    detail = ""
    detail_sub = ""
    allow_rule = {"tool": tool_name.replace("mcp__acp__", ""), "action": "allow"}
    allow_rules = []

    normalized = tool_name.replace("mcp__acp__", "")

    if normalized == "Bash":
        command = tool_input.get("command", "")
        detail = command
        detail_sub = ""
        # Parse compound commands into individual rules
        parts = re.split(r'\||\&\&', command)
        rules = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            prefix = permission_rules.extract_bash_prefix(part)
            if not prefix:
                continue
            rule = {"tool": "Bash", "prefix": prefix, "action": "allow"}
            if rule not in rules:
                rules.append(rule)
        allow_rules = rules
        allow_rule = rules[0] if rules else {"tool": "Bash", "action": "allow"}

    elif normalized == "Write":
        file_path = tool_input.get("file_path", "")
        detail = file_path
        allow_rule = {"tool": "Write", "action": "allow"}

    elif normalized == "Edit":
        file_path = tool_input.get("file_path", "")
        old_string = tool_input.get("old_string", "")
        detail = file_path
        detail_sub = "\n".join(old_string.split("\n")[:5]) if old_string else ""
        allow_rule = {"tool": "Edit", "action": "allow"}

    elif tool_name == "ExitPlanMode":
        plan = tool_input.get("plan", "")
        detail = plan if plan else "Exit plan mode"
        allowed = tool_input.get("allowedPrompts", [])
        if allowed:
            parts = [f"{p.get('tool', '?')}: {p.get('prompt', '?')}" for p in allowed]
            detail_sub = "Requested permissions: " + ", ".join(parts)
        allow_rule = {"tool": "ExitPlanMode", "action": "allow"}

    elif tool_name == "AskUserQuestion":
        questions = tool_input.get("questions", [])
        if questions:
            lines = []
            for q in questions:
                lines.append(f"Q: {q.get('question', '')}")
                for opt in q.get("options", []):
                    lines.append(f"  - {opt.get('label', '')} — {opt.get('description', '')}")
            detail = "\n".join(lines)
        else:
            detail = json.dumps(tool_input, indent=2)[:500]
        allow_rule = {"tool": "AskUserQuestion", "action": "allow"}

    elif tool_name == "WebFetch":
        detail = tool_input.get("url", "")
        detail_sub = tool_input.get("prompt", "")
        allow_rule = {"tool": "WebFetch", "action": "allow"}

    elif tool_name == "WebSearch":
        detail = tool_input.get("query", "")
        allow_rule = {"tool": "WebSearch", "action": "allow"}

    else:
        items = [f"{k}: {v}" for k, v in list(tool_input.items())[:10]]
        detail = "\n".join(items)
        allow_rule = {"tool": normalized, "action": "allow"}

    return detail, detail_sub, allow_rule, allow_rules


def _format_rule_display(rule):
    """Format a rule dict for display in the UI."""
    tool = rule.get("tool", "")
    prefix = rule.get("prefix", "")
    if prefix:
        return f"{tool}: {prefix}"
    return tool


def main():
    import signal
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    os.makedirs(QUEUE_DIR, exist_ok=True)

    try:
        input_data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    tool_name = input_data.get("tool_name", "Unknown")
    tool_input = input_data.get("tool_input", {})

    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, ValueError):
            tool_input = {}

    project_dir = os.getcwd()
    session_id = input_data.get("session_id", "") or str(find_claude_pid())

    # Build detail and rules for display/storage
    detail, detail_sub, allow_rule, allow_rules = build_detail(tool_name, tool_input)

    # ── Auto-allow tiers (first match wins) ──

    # Tier 1: WebUI rules (repo + user + project levels, checked locally)
    result = permission_rules.resolve(tool_name, tool_input, project_dir)
    if result == "allow":
        allow_response()
    if result == "deny":
        deny_response("Denied by WebUI permission rule")

    # Tier 2: Tmux allowlist (WebUI uses tmux for prompt delivery)
    if tool_name in ("Bash", "mcp__acp__Bash"):
        command = tool_input.get("command", "").strip()
        first_token = command.split()[0] if command.split() else ""
        if os.path.basename(first_token) == "tmux":
            allow_response()

    # Tier 3: Session rules (queried via server API)
    # This call also doubles as the server-online check (tier 4).
    try:
        query_params = {
            "session_id": str(session_id),
            "tool_name": tool_name,
            "tool_input": json.dumps(tool_input),
        }
        req = urllib.request.Request(
            f"{SERVER}/api/check-auto-allow?{urllib.parse.urlencode(query_params)}")
        resp = urllib.request.urlopen(req, timeout=2)
        data = json.loads(resp.read())
        if data.get("auto_allow"):
            allow_response()
        elif data.get("auto_deny"):
            deny_response("Denied by session rule")
    except Exception:
        # Tier 4: Server offline — allow everything so Claude keeps working
        allow_response()

    # Dedup: if this session already has a pending request for the same tool+input,
    # piggyback on it instead of creating a duplicate.
    existing_rid = None
    for fpath in glob.glob(os.path.join(QUEUE_DIR, "*.request.json")):
        resp_path = fpath.replace(".request.json", ".response.json")
        if os.path.exists(resp_path):
            continue
        try:
            with open(fpath) as f:
                existing = json.load(f)
            if (str(existing.get("session_id", "")) == str(session_id)
                    and existing.get("tool_name") == tool_name
                    and existing.get("tool_input") == tool_input):
                existing_rid = existing.get("id", "")
                break
        except (json.JSONDecodeError, IOError):
            continue

    if existing_rid:
        response_file = os.path.join(QUEUE_DIR, f"{existing_rid}.response.json")
        elapsed = 0
        while elapsed < TIMEOUT:
            if os.path.isfile(response_file):
                try:
                    with open(response_file) as f:
                        resp = json.load(f)
                    decision = resp.get("decision", "deny")
                    if decision in ("allow", "always"):
                        allow_response()
                    else:
                        deny_response(resp.get("message", "User denied"))
                except (json.JSONDecodeError, IOError):
                    pass
            time.sleep(0.5)
            elapsed += 1
        deny_response("Approval timed out")

    # Generate request ID
    try:
        request_id = str(uuid.uuid4())
    except Exception:
        request_id = str(int(time.time() * 1e9))

    request_file = os.path.join(QUEUE_DIR, f"{request_id}.request.json")
    response_file = os.path.join(QUEUE_DIR, f"{request_id}.response.json")

    def cleanup():
        try:
            os.remove(request_file)
        except OSError:
            pass
    atexit.register(cleanup)

    # Format display strings for UI
    if allow_rules:
        allow_pattern = ", ".join(_format_rule_display(r) for r in allow_rules)
        allow_patterns_display = [_format_rule_display(r) for r in allow_rules]
    else:
        allow_pattern = _format_rule_display(allow_rule)
        allow_patterns_display = []

    request_data = {
        "id": request_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "detail": detail,
        "detail_sub": detail_sub,
        "allow_rule": allow_rule,
        "allow_rules": allow_rules if allow_rules else [],
        # Display strings for UI (human-readable)
        "allow_pattern": allow_pattern,
        "allow_patterns": allow_patterns_display,
        "timestamp": int(time.time()),
        "pid": os.getpid(),
        "session_id": session_id,
        "project_dir": project_dir,
    }
    tmp_file = request_file + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(request_data, f)
    os.replace(tmp_file, request_file)

    # Poll for response
    elapsed = 0
    while elapsed < TIMEOUT:
        if os.path.isfile(response_file):
            try:
                with open(response_file) as f:
                    resp = json.load(f)
            except (json.JSONDecodeError, IOError):
                time.sleep(0.5)
                elapsed += 1
                continue

            decision = resp.get("decision", "deny")
            message = resp.get("message", "User denied via web UI")

            try:
                os.remove(request_file)
            except OSError:
                pass
            try:
                os.remove(response_file)
            except OSError:
                pass
            atexit.unregister(cleanup)

            if decision in ("allow", "always"):
                allow_response()
            else:
                deny_response(message)

        time.sleep(0.5)
        elapsed += 1

    try:
        os.remove(request_file)
    except OSError:
        pass
    atexit.unregister(cleanup)
    deny_response("Approval timed out")


if __name__ == "__main__":
    main()
