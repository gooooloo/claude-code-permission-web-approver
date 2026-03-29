"""
4-level permission auto-allow rule engine for Claude Code WebUI.

Levels (priority high to low): session > project > user > repo.
Each level has pattern rules and smart rules. Within a level, rules are
checked before smart_rules. First match across all levels wins.

Rule format:
    {"rules": [{"tool": "Bash", "prefix": "git commit", "action": "allow"}, ...],
     "smart_rules": {"readonly_tools": "allow", "readonly_bash": "allow", ...}}
"""

import json
import os
import re


# ── Path helpers ──

def repo_rules_path():
    """Path to repo-level auto-allow.json (shipped with webui code)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto-allow.json")


def user_rules_path():
    """Path to user-level ~/.claude/webui-allow.json."""
    return os.path.join(os.path.expanduser("~"), ".claude", "webui-allow.json")


def project_rules_path(project_dir):
    """Path to project-level <project>/.claude/webui-allow.json."""
    return os.path.join(project_dir, ".claude", "webui-allow.json")


# ── Loading ──

_EMPTY = {"rules": [], "smart_rules": {}}


def load_rules(path):
    """Load rules from a JSON file. Returns empty ruleset on missing/invalid."""
    if not path or not os.path.isfile(path):
        return {"rules": [], "smart_rules": {}}
    try:
        with open(path) as f:
            data = json.load(f)
        rules = data.get("rules", [])
        smart_rules = data.get("smart_rules", {})
        return {"rules": rules, "smart_rules": smart_rules}
    except (json.JSONDecodeError, IOError, OSError):
        return {"rules": [], "smart_rules": {}}


def _save_rules(path, data):
    """Atomically write rules to a JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ── Smart rule constants (moved from hook-permission-request.py) ──

READONLY_COMMANDS = {
    "cat", "head", "tail", "less", "more", "wc", "file", "stat", "du", "df",
    "ls", "tree", "find", "realpath", "dirname", "basename",
    "grep", "rg", "ag", "fgrep", "egrep",
    "echo", "printf", "date", "whoami", "hostname", "uname", "env", "printenv",
    "which", "type", "command", "true", "false", "test",
    "npm", "pip", "pip3", "cargo", "go", "python", "python3", "node", "ruby", "java", "javac",
}

READONLY_GIT_SUBCOMMANDS = {
    "log", "diff", "status", "show", "branch", "tag", "remote", "stash",
    "blame", "shortlog", "describe", "rev-parse", "rev-list", "ls-files",
    "ls-tree", "cat-file", "config",
}

DANGEROUS_COMMANDS = {
    "rm", "rmdir", "mv", "chmod", "chown", "chgrp", "mkfs", "dd",
    "shutdown", "reboot", "kill", "killall", "pkill",
    "curl", "wget",
    "ssh", "scp", "rsync",
    "sudo", "su", "doas",
}

READONLY_TOOLS = {"Read", "Glob", "Grep", "mcp__acp__Read", "mcp__acp__Glob", "mcp__acp__Grep"}


# ── Bash helpers ──

def is_readonly_bash(command):
    """Check if a Bash command (possibly compound) is read-only."""
    parts = re.split(r'\||&&|\|\||;', command)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        first_line = part.split("\n")[0].strip()
        tokens = first_line.split()
        if not tokens:
            continue
        base = os.path.basename(tokens[0])
        if not base:
            continue
        if base in DANGEROUS_COMMANDS:
            return False
        if base == "sed":
            if "-i" in tokens or any(t.startswith("-i") for t in tokens[1:]):
                return False
            continue
        if base in ("awk", "gawk", "mawk", "nawk"):
            continue
        if base == "git":
            sub = ""
            for t in tokens[1:]:
                if not t.startswith("-"):
                    sub = t
                    break
            if sub not in READONLY_GIT_SUBCOMMANDS:
                return False
            continue
        if base in READONLY_COMMANDS:
            continue
        return False
    return True


def is_project_file(file_path, project_dir):
    """Check if a file path is within the project directory."""
    if not file_path or not project_dir:
        return False
    try:
        real_file = os.path.realpath(file_path)
        real_cwd = os.path.realpath(project_dir)
        return real_file.startswith(real_cwd + os.sep) or real_file == real_cwd
    except (ValueError, OSError):
        return False


def extract_bash_prefix(command):
    """Extract 'base subcommand' prefix from a single (non-compound) command.

    Examples:
        'git commit -m test' -> 'git commit'
        'ls -la'             -> 'ls'
        'npm install foo'    -> 'npm install'
    """
    command = command.strip()
    if not command:
        return ""
    first_line = command.split("\n")[0].strip()
    tokens = first_line.split()
    if not tokens:
        return ""
    base = os.path.basename(tokens[0])
    if not base:
        return ""
    sub = ""
    for t in tokens[1:]:
        if not t.startswith(("-", "/", ".")):
            sub = t
            break
    if sub:
        return f"{base} {sub}"
    return base


# ── Matching ──

def match_rule(tool_name, tool_input, rule, project_dir=None):
    """Check if a single rule matches the given tool call.

    For Bash: matches if the command's extracted prefix starts with rule.prefix.
    For Write/Edit with prefix: matches if file_path starts with rule.prefix (glob via fnmatch).
    For other tools: matches on tool name only (prefix ignored).
    """
    rule_tool = rule.get("tool", "")
    # Normalize MCP tool names
    normalized = tool_name.replace("mcp__acp__", "")
    rule_normalized = rule_tool.replace("mcp__acp__", "")
    if normalized != rule_normalized:
        return False

    prefix = rule.get("prefix", "")

    if normalized in ("Bash",):
        if not prefix:
            # Blanket Bash rule — matches any Bash command
            return True
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        # For compound commands, each part is checked separately via check_compound_bash
        # Here we match a single command
        cmd_prefix = extract_bash_prefix(command)
        return cmd_prefix.startswith(prefix) if cmd_prefix else False

    if normalized in ("Write", "Edit") and prefix:
        # Path-based matching
        import fnmatch
        file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
        return fnmatch.fnmatch(file_path, prefix) if file_path else False

    # Non-Bash, no prefix → tool name match only
    return True


def _evaluate_smart_rules(tool_name, tool_input, project_dir, smart_rules):
    """Evaluate smart rules for a tool call. Returns 'allow', 'deny', or None."""
    normalized = tool_name.replace("mcp__acp__", "")

    # readonly_tools
    if normalized in ("Read", "Glob", "Grep"):
        action = smart_rules.get("readonly_tools")
        if action:
            return action

    # readonly_bash
    if normalized == "Bash":
        action = smart_rules.get("readonly_bash")
        if action:
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            if command and is_readonly_bash(command):
                return action

    # project_internal_edit
    if normalized in ("Write", "Edit"):
        action = smart_rules.get("project_internal_edit")
        if action:
            file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
            if is_project_file(file_path, project_dir):
                return action

    return None


def check_level(tool_name, tool_input, level_config, project_dir=None):
    """Check one level of rules. Returns 'allow', 'deny', or None.

    Checks rules first (first match wins), then smart_rules.
    For compound Bash commands, splits and checks each part.
    """
    if not level_config:
        return None

    rules = level_config.get("rules", [])
    smart_rules = level_config.get("smart_rules", {})

    # Check pattern rules
    normalized = tool_name.replace("mcp__acp__", "")
    if normalized == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command", "")
        if command:
            result = _check_compound_bash_rules(command, rules)
            if result is not None:
                return result
    else:
        for rule in rules:
            if match_rule(tool_name, tool_input, rule, project_dir):
                return rule.get("action", "allow")

    # Check smart rules
    return _evaluate_smart_rules(tool_name, tool_input, project_dir, smart_rules)


def _check_compound_bash_rules(command, rules):
    """Check compound Bash command against rules.

    Splits on &&, |, ||, ;. ALL parts must match and be allowed.
    If any part matches a deny rule, deny the whole thing.
    If any part has no matching rule, return None.
    """
    parts = re.split(r'\||&&|\|\||;', command)
    non_empty = [p.strip() for p in parts if p.strip()]
    if not non_empty:
        return None

    for part in non_empty:
        part_input = {"command": part}
        part_result = None
        for rule in rules:
            if match_rule("Bash", part_input, rule):
                part_result = rule.get("action", "allow")
                break
        if part_result == "deny":
            return "deny"
        if part_result is None:
            return None

    return "allow"


def resolve(tool_name, tool_input, project_dir, session_rules=None):
    """Resolve permission across all 4 levels. Returns 'allow', 'deny', or None.

    Priority: session > project > user > repo.
    """
    levels = []

    # Session level (in-memory, passed in)
    if session_rules:
        levels.append(session_rules)

    # Project level
    if project_dir:
        levels.append(load_rules(project_rules_path(project_dir)))

    # User level
    levels.append(load_rules(user_rules_path()))

    # Repo level
    levels.append(load_rules(repo_rules_path()))

    for level_config in levels:
        result = check_level(tool_name, tool_input, level_config, project_dir)
        if result is not None:
            return result

    return None


# ── CRUD operations ──

def add_rule(path, rule):
    """Add a rule to a rules file."""
    data = load_rules(path)
    data["rules"].append(rule)
    _save_rules(path, data)


def remove_rule(path, index):
    """Remove a rule by index from a rules file."""
    data = load_rules(path)
    if 0 <= index < len(data["rules"]):
        data["rules"].pop(index)
        _save_rules(path, data)


def update_rule(path, index, rule):
    """Update a rule at a given index."""
    data = load_rules(path)
    if 0 <= index < len(data["rules"]):
        data["rules"][index] = rule
        _save_rules(path, data)


def move_rule(from_path, from_index, to_path):
    """Move a rule from one level to another."""
    from_data = load_rules(from_path)
    if not (0 <= from_index < len(from_data["rules"])):
        return
    rule = from_data["rules"].pop(from_index)
    _save_rules(from_path, from_data)

    to_data = load_rules(to_path)
    to_data["rules"].append(rule)
    _save_rules(to_path, to_data)


def set_smart_rule(path, key, action):
    """Set a smart rule in a rules file."""
    data = load_rules(path)
    data["smart_rules"][key] = action
    _save_rules(path, data)


def remove_smart_rule(path, key):
    """Remove a smart rule from a rules file."""
    data = load_rules(path)
    if key in data["smart_rules"]:
        del data["smart_rules"][key]
        _save_rules(path, data)
