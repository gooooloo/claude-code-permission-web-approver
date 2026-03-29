"""Tests for permission_rules.py — 4-level auto-allow rule engine."""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import permission_rules as pr


# ── extract_bash_prefix ──


class TestExtractBashPrefix:
    def test_simple_command(self):
        assert pr.extract_bash_prefix("ls -la") == "ls"

    def test_command_with_subcommand(self):
        assert pr.extract_bash_prefix("git commit -m 'test'") == "git commit"

    def test_command_with_path_arg(self):
        # /path and .path args are skipped (treated as flags/paths, not subcommands)
        assert pr.extract_bash_prefix("cat /tmp/foo.txt") == "cat"

    def test_npm_install(self):
        assert pr.extract_bash_prefix("npm install foo") == "npm install"

    def test_no_subcommand(self):
        assert pr.extract_bash_prefix("ls") == "ls"

    def test_empty(self):
        assert pr.extract_bash_prefix("") == ""

    def test_multiline(self):
        assert pr.extract_bash_prefix("git status\nmore stuff") == "git status"

    def test_flag_only_args(self):
        assert pr.extract_bash_prefix("grep -r -n pattern") == "grep pattern"

    def test_dotfile_arg_skipped(self):
        assert pr.extract_bash_prefix("cat ./foo.txt") == "cat"


# ── match_rule ──


class TestMatchRule:
    def test_bash_prefix_match(self):
        rule = {"tool": "Bash", "prefix": "git commit", "action": "allow"}
        assert pr.match_rule("Bash", {"command": "git commit -m 'test'"}, rule) is True

    def test_bash_prefix_no_match(self):
        rule = {"tool": "Bash", "prefix": "git commit", "action": "allow"}
        assert pr.match_rule("Bash", {"command": "git push origin"}, rule) is False

    def test_bash_blanket(self):
        rule = {"tool": "Bash", "action": "allow"}
        assert pr.match_rule("Bash", {"command": "rm -rf /"}, rule) is True

    def test_tool_name_match(self):
        rule = {"tool": "Write", "action": "allow"}
        assert pr.match_rule("Write", {"file_path": "/any/path"}, rule) is True

    def test_tool_name_mismatch(self):
        rule = {"tool": "Write", "action": "allow"}
        assert pr.match_rule("Read", {}, rule) is False

    def test_mcp_prefix_normalized(self):
        rule = {"tool": "Bash", "prefix": "git log", "action": "allow"}
        assert pr.match_rule("mcp__acp__Bash", {"command": "git log --oneline"}, rule) is True

    def test_write_with_path_prefix(self):
        rule = {"tool": "Write", "prefix": "/home/user/proj/*", "action": "allow"}
        assert pr.match_rule("Write", {"file_path": "/home/user/proj/src/main.py"}, rule) is True

    def test_write_path_outside(self):
        rule = {"tool": "Write", "prefix": "/home/user/proj/*", "action": "allow"}
        assert pr.match_rule("Write", {"file_path": "/etc/passwd"}, rule) is False

    def test_edit_with_path_prefix(self):
        rule = {"tool": "Edit", "prefix": "/home/user/proj/*", "action": "allow"}
        assert pr.match_rule("Edit", {"file_path": "/home/user/proj/foo.py"}, rule) is True

    def test_bash_prefix_partial_no_false_positive(self):
        # "git com" should not match "git commit"
        rule = {"tool": "Bash", "prefix": "gitcommando", "action": "allow"}
        assert pr.match_rule("Bash", {"command": "git commit -m 'test'"}, rule) is False

    def test_non_dict_tool_input(self):
        rule = {"tool": "Bash", "prefix": "git", "action": "allow"}
        assert pr.match_rule("Bash", "not a dict", rule) is False


# ── is_readonly_bash ──


class TestIsReadonlyBash:
    def test_simple_readonly(self):
        assert pr.is_readonly_bash("ls -la") is True

    def test_git_log(self):
        assert pr.is_readonly_bash("git log --oneline") is True

    def test_dangerous_rm(self):
        assert pr.is_readonly_bash("rm -rf /tmp/foo") is False

    def test_compound_all_readonly(self):
        assert pr.is_readonly_bash("ls -la && cat foo.txt | grep bar") is True

    def test_compound_with_dangerous(self):
        assert pr.is_readonly_bash("ls -la && rm foo.txt") is False

    def test_git_push_not_readonly(self):
        assert pr.is_readonly_bash("git push origin main") is False

    def test_sed_inplace_not_readonly(self):
        assert pr.is_readonly_bash("sed -i 's/foo/bar/' file.txt") is False

    def test_sed_without_inplace(self):
        assert pr.is_readonly_bash("sed 's/foo/bar/' file.txt") is True

    def test_empty(self):
        assert pr.is_readonly_bash("") is True

    def test_unknown_command(self):
        assert pr.is_readonly_bash("my-custom-script.sh") is False


# ── is_project_file ──


class TestIsProjectFile:
    def test_inside(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        assert pr.is_project_file(os.path.join(project, "src", "main.py"), project) is True

    def test_outside(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        assert pr.is_project_file("/etc/passwd", project) is False

    def test_traversal(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        assert pr.is_project_file(os.path.join(project, "..", "secret"), project) is False

    def test_empty(self):
        assert pr.is_project_file("", "/home") is False
        assert pr.is_project_file("/home/file", "") is False


# ── check_level ──


class TestCheckLevel:
    def test_rule_match(self):
        config = {"rules": [{"tool": "Bash", "prefix": "git commit", "action": "allow"}], "smart_rules": {}}
        assert pr.check_level("Bash", {"command": "git commit -m 'x'"}, config) == "allow"

    def test_rule_deny(self):
        config = {"rules": [{"tool": "Bash", "prefix": "rm", "action": "deny"}], "smart_rules": {}}
        assert pr.check_level("Bash", {"command": "rm -rf /"}, config) == "deny"

    def test_smart_rule_fallback(self):
        config = {"rules": [], "smart_rules": {"readonly_tools": "allow"}}
        assert pr.check_level("Read", {}, config) == "allow"

    def test_rule_before_smart(self):
        # Rule says deny Write, smart says allow project_internal_edit
        config = {
            "rules": [{"tool": "Write", "action": "deny"}],
            "smart_rules": {"project_internal_edit": "allow"},
        }
        assert pr.check_level("Write", {"file_path": "/proj/foo.py"}, config, "/proj") == "deny"

    def test_no_match(self):
        config = {"rules": [{"tool": "Bash", "prefix": "git", "action": "allow"}], "smart_rules": {}}
        assert pr.check_level("Write", {"file_path": "/foo"}, config) is None

    def test_empty_config(self):
        assert pr.check_level("Read", {}, None) is None
        assert pr.check_level("Read", {}, {}) is None

    def test_compound_bash_all_allowed(self):
        config = {
            "rules": [
                {"tool": "Bash", "prefix": "git", "action": "allow"},
                {"tool": "Bash", "prefix": "echo", "action": "allow"},
            ],
            "smart_rules": {},
        }
        assert pr.check_level("Bash", {"command": "git status && echo done"}, config) == "allow"

    def test_compound_bash_partial_deny(self):
        config = {
            "rules": [
                {"tool": "Bash", "prefix": "git", "action": "allow"},
                {"tool": "Bash", "prefix": "rm", "action": "deny"},
            ],
            "smart_rules": {},
        }
        assert pr.check_level("Bash", {"command": "git status && rm foo"}, config) == "deny"

    def test_compound_bash_partial_no_match(self):
        config = {
            "rules": [{"tool": "Bash", "prefix": "git", "action": "allow"}],
            "smart_rules": {},
        }
        # "rm foo" has no matching rule → whole compound returns None
        assert pr.check_level("Bash", {"command": "git status && rm foo"}, config) is None

    def test_smart_readonly_bash(self):
        config = {"rules": [], "smart_rules": {"readonly_bash": "allow"}}
        assert pr.check_level("Bash", {"command": "ls -la"}, config) == "allow"
        assert pr.check_level("Bash", {"command": "rm foo"}, config) is None

    def test_smart_project_internal_edit(self, tmp_path):
        project = str(tmp_path)
        config = {"rules": [], "smart_rules": {"project_internal_edit": "allow"}}
        assert pr.check_level("Write", {"file_path": os.path.join(project, "f.py")}, config, project) == "allow"
        assert pr.check_level("Write", {"file_path": "/etc/passwd"}, config, project) is None

    def test_smart_readonly_bash_deny(self):
        """Smart rule can also deny."""
        config = {"rules": [], "smart_rules": {"readonly_bash": "deny"}}
        assert pr.check_level("Bash", {"command": "ls -la"}, config) == "deny"


# ── resolve (4-level priority) ──


class TestResolve:
    def test_session_overrides_project(self, tmp_path):
        # Project says deny git commit, session says allow
        proj_dir = str(tmp_path / "proj")
        os.makedirs(os.path.join(proj_dir, ".claude"), exist_ok=True)
        proj_rules = os.path.join(proj_dir, ".claude", "webui-allow.json")
        with open(proj_rules, "w") as f:
            json.dump({"rules": [{"tool": "Bash", "prefix": "git commit", "action": "deny"}], "smart_rules": {}}, f)

        session = {"rules": [{"tool": "Bash", "prefix": "git commit", "action": "allow"}], "smart_rules": {}}
        result = pr.resolve("Bash", {"command": "git commit -m 'x'"}, proj_dir, session_rules=session)
        assert result == "allow"

    def test_project_overrides_user(self, tmp_path, monkeypatch):
        proj_dir = str(tmp_path / "proj")
        os.makedirs(os.path.join(proj_dir, ".claude"), exist_ok=True)
        proj_rules = os.path.join(proj_dir, ".claude", "webui-allow.json")
        with open(proj_rules, "w") as f:
            json.dump({"rules": [{"tool": "Write", "action": "deny"}], "smart_rules": {}}, f)

        # Mock user_rules_path to use tmp
        user_dir = str(tmp_path / "user_claude")
        os.makedirs(user_dir, exist_ok=True)
        user_file = os.path.join(user_dir, "webui-allow.json")
        with open(user_file, "w") as f:
            json.dump({"rules": [{"tool": "Write", "action": "allow"}], "smart_rules": {}}, f)
        monkeypatch.setattr(pr, "user_rules_path", lambda: user_file)

        result = pr.resolve("Write", {"file_path": "/any"}, proj_dir)
        assert result == "deny"

    def test_no_match_returns_none(self, tmp_path, monkeypatch):
        proj_dir = str(tmp_path / "proj")
        os.makedirs(proj_dir, exist_ok=True)
        # Empty user and repo rules
        monkeypatch.setattr(pr, "user_rules_path", lambda: str(tmp_path / "nonexistent"))
        monkeypatch.setattr(pr, "repo_rules_path", lambda: str(tmp_path / "nonexistent2"))
        result = pr.resolve("CustomTool", {}, proj_dir)
        assert result is None

    def test_repo_smart_rules_apply(self, tmp_path, monkeypatch):
        proj_dir = str(tmp_path / "proj")
        os.makedirs(proj_dir, exist_ok=True)
        # No project or user rules
        monkeypatch.setattr(pr, "user_rules_path", lambda: str(tmp_path / "nonexistent"))
        # Repo has readonly_tools smart rule
        repo_file = str(tmp_path / "repo-allow.json")
        with open(repo_file, "w") as f:
            json.dump({"rules": [], "smart_rules": {"readonly_tools": "allow"}}, f)
        monkeypatch.setattr(pr, "repo_rules_path", lambda: repo_file)

        result = pr.resolve("Read", {}, proj_dir)
        assert result == "allow"

    def test_deny_at_higher_level_blocks_lower_allow(self, tmp_path, monkeypatch):
        proj_dir = str(tmp_path / "proj")
        os.makedirs(os.path.join(proj_dir, ".claude"), exist_ok=True)
        # Project denies WebFetch
        proj_rules = os.path.join(proj_dir, ".claude", "webui-allow.json")
        with open(proj_rules, "w") as f:
            json.dump({"rules": [{"tool": "WebFetch", "action": "deny"}], "smart_rules": {}}, f)
        # User allows WebFetch
        user_file = str(tmp_path / "user-allow.json")
        with open(user_file, "w") as f:
            json.dump({"rules": [{"tool": "WebFetch", "action": "allow"}], "smart_rules": {}}, f)
        monkeypatch.setattr(pr, "user_rules_path", lambda: user_file)
        monkeypatch.setattr(pr, "repo_rules_path", lambda: str(tmp_path / "nonexistent"))

        result = pr.resolve("WebFetch", {"url": "https://example.com"}, proj_dir)
        assert result == "deny"


# ── load_rules ──


class TestLoadRules:
    def test_valid_file(self, tmp_rules_file):
        path = tmp_rules_file(
            rules=[{"tool": "Bash", "prefix": "git", "action": "allow"}],
            smart_rules={"readonly_tools": "allow"},
        )
        data = pr.load_rules(path)
        assert len(data["rules"]) == 1
        assert data["smart_rules"]["readonly_tools"] == "allow"

    def test_missing_file(self):
        data = pr.load_rules("/nonexistent/path.json")
        assert data["rules"] == []
        assert data["smart_rules"] == {}

    def test_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        data = pr.load_rules(str(bad))
        assert data["rules"] == []

    def test_empty_path(self):
        data = pr.load_rules("")
        assert data["rules"] == []


# ── CRUD ──


class TestCRUD:
    def test_add_rule(self, tmp_rules_file):
        path = tmp_rules_file()
        pr.add_rule(path, {"tool": "Bash", "prefix": "git commit", "action": "allow"})
        data = pr.load_rules(path)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["prefix"] == "git commit"

    def test_remove_rule(self, tmp_rules_file):
        path = tmp_rules_file(rules=[
            {"tool": "Bash", "prefix": "git", "action": "allow"},
            {"tool": "Write", "action": "allow"},
        ])
        pr.remove_rule(path, 0)
        data = pr.load_rules(path)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["tool"] == "Write"

    def test_update_rule(self, tmp_rules_file):
        path = tmp_rules_file(rules=[{"tool": "Bash", "prefix": "git", "action": "allow"}])
        pr.update_rule(path, 0, {"tool": "Bash", "prefix": "git", "action": "deny"})
        data = pr.load_rules(path)
        assert data["rules"][0]["action"] == "deny"

    def test_move_rule(self, tmp_rules_file):
        from_path = tmp_rules_file(rules=[
            {"tool": "Bash", "prefix": "git", "action": "allow"},
            {"tool": "Write", "action": "allow"},
        ])
        to_path = tmp_rules_file(subdir="dest")
        pr.move_rule(from_path, 0, to_path)
        from_data = pr.load_rules(from_path)
        to_data = pr.load_rules(to_path)
        assert len(from_data["rules"]) == 1
        assert len(to_data["rules"]) == 1
        assert to_data["rules"][0]["prefix"] == "git"

    def test_set_smart_rule(self, tmp_rules_file):
        path = tmp_rules_file()
        pr.set_smart_rule(path, "readonly_bash", "allow")
        data = pr.load_rules(path)
        assert data["smart_rules"]["readonly_bash"] == "allow"

    def test_remove_smart_rule(self, tmp_rules_file):
        path = tmp_rules_file(smart_rules={"readonly_bash": "allow", "readonly_tools": "allow"})
        pr.remove_smart_rule(path, "readonly_bash")
        data = pr.load_rules(path)
        assert "readonly_bash" not in data["smart_rules"]
        assert "readonly_tools" in data["smart_rules"]

    def test_add_rule_creates_file(self, tmp_path):
        path = str(tmp_path / "new_dir" / "webui-allow.json")
        pr.add_rule(path, {"tool": "Read", "action": "allow"})
        data = pr.load_rules(path)
        assert len(data["rules"]) == 1
