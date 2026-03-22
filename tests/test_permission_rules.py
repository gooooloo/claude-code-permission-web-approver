"""Tests for hook-permission-request.py — auto-allow logic, pattern matching, smart rules."""

import json
import os
import sys

import importlib.util

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _import_hook(name):
    path = os.path.join(PROJECT_ROOT, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _import_hook("hook-permission-request")


# ── build_detail ──


class TestBuildDetail:
    def test_bash_simple_command(self):
        detail, detail_sub, pattern, patterns = hook.build_detail(
            "Bash", {"command": "git status"}
        )
        assert detail == "git status"
        assert "Bash(git status:*)" in patterns

    def test_bash_compound_command(self):
        detail, detail_sub, pattern, patterns = hook.build_detail(
            "Bash", {"command": "git add . && git commit -m 'test'"}
        )
        assert "Bash(git add:*)" in patterns
        assert "Bash(git commit:*)" in patterns

    def test_bash_pipe(self):
        _, _, _, patterns = hook.build_detail(
            "Bash", {"command": "cat foo.txt | grep bar"}
        )
        assert "Bash(cat foo.txt:*)" in patterns
        assert "Bash(grep bar:*)" in patterns

    def test_write_tool(self):
        detail, _, pattern, _ = hook.build_detail(
            "Write", {"file_path": "/tmp/test.txt"}
        )
        assert detail == "/tmp/test.txt"
        assert pattern == "Write(/tmp/test.txt)"

    def test_edit_tool(self):
        detail, detail_sub, pattern, _ = hook.build_detail(
            "Edit", {"file_path": "/tmp/test.txt", "old_string": "line1\nline2\nline3"}
        )
        assert detail == "/tmp/test.txt"
        assert "line1" in detail_sub
        assert pattern == "Edit(/tmp/test.txt)"

    def test_webfetch_tool(self):
        detail, detail_sub, pattern, _ = hook.build_detail(
            "WebFetch", {"url": "https://example.com", "prompt": "read it"}
        )
        assert detail == "https://example.com"
        assert detail_sub == "read it"
        assert pattern == "WebFetch"

    def test_websearch_tool(self):
        detail, _, pattern, _ = hook.build_detail(
            "WebSearch", {"query": "python testing"}
        )
        assert detail == "python testing"
        assert pattern == "WebSearch"

    def test_unknown_tool(self):
        detail, _, pattern, _ = hook.build_detail(
            "CustomTool", {"key1": "val1", "key2": "val2"}
        )
        assert "key1: val1" in detail
        assert pattern == "CustomTool"

    def test_ask_user_question(self):
        detail, _, pattern, _ = hook.build_detail(
            "AskUserQuestion",
            {"questions": [{"question": "Continue?", "options": [{"label": "Yes", "description": "proceed"}]}]},
        )
        assert "Continue?" in detail
        assert "Yes" in detail
        assert pattern == "AskUserQuestion"

    def test_exit_plan_mode(self):
        detail, detail_sub, pattern, _ = hook.build_detail(
            "ExitPlanMode",
            {"plan": "My plan", "allowedPrompts": [{"tool": "Bash", "prompt": "ls"}]},
        )
        assert detail == "My plan"
        assert "Bash" in detail_sub
        assert pattern == "ExitPlanMode"


# ── _match_allow_pattern ──


class TestMatchAllowPattern:
    def test_exact_tool_name(self):
        assert hook._match_allow_pattern("Read", "anything", "Read") is True

    def test_tool_name_mismatch(self):
        assert hook._match_allow_pattern("Read", "anything", "Write") is False

    def test_glob_with_colon_star(self):
        assert hook._match_allow_pattern("Bash", "git status", "Bash(git status:*)") is True

    def test_glob_prefix_match(self):
        assert hook._match_allow_pattern("Bash", "git commit -m 'test'", "Bash(git commit:*)") is True

    def test_glob_no_match(self):
        assert hook._match_allow_pattern("Bash", "rm -rf /", "Bash(git:*)") is False

    def test_write_path_pattern(self):
        assert hook._match_allow_pattern("Write", "/home/user/proj/foo.py", "Write(/home/user/proj/*)") is True

    def test_write_path_outside(self):
        assert hook._match_allow_pattern("Write", "/etc/passwd", "Write(/home/user/proj/*)") is False

    def test_empty_pattern(self):
        assert hook._match_allow_pattern("Bash", "ls", "") is False


# ── _is_readonly_bash ──


class TestIsReadonlyBash:
    def test_simple_readonly(self):
        assert hook._is_readonly_bash("ls -la") is True

    def test_cat_file(self):
        assert hook._is_readonly_bash("cat foo.txt") is True

    def test_grep_search(self):
        assert hook._is_readonly_bash("grep -r 'pattern' .") is True

    def test_git_log(self):
        assert hook._is_readonly_bash("git log --oneline") is True

    def test_git_status(self):
        assert hook._is_readonly_bash("git status") is True

    def test_git_diff(self):
        assert hook._is_readonly_bash("git diff HEAD") is True

    def test_dangerous_rm(self):
        assert hook._is_readonly_bash("rm -rf /tmp/foo") is False

    def test_dangerous_curl(self):
        assert hook._is_readonly_bash("curl https://example.com") is False

    def test_dangerous_sudo(self):
        assert hook._is_readonly_bash("sudo apt install foo") is False

    def test_compound_all_readonly(self):
        assert hook._is_readonly_bash("ls -la && cat foo.txt | grep bar") is True

    def test_compound_with_dangerous(self):
        assert hook._is_readonly_bash("ls -la && rm foo.txt") is False

    def test_pipe_all_readonly(self):
        assert hook._is_readonly_bash("cat file | head -20 | wc -l") is True

    def test_git_push_not_readonly(self):
        assert hook._is_readonly_bash("git push origin main") is False

    def test_git_commit_not_readonly(self):
        assert hook._is_readonly_bash("git commit -m 'msg'") is False

    def test_sed_inplace_not_readonly(self):
        assert hook._is_readonly_bash("sed -i 's/foo/bar/' file.txt") is False

    def test_sed_without_inplace_is_readonly(self):
        assert hook._is_readonly_bash("sed 's/foo/bar/' file.txt") is True

    def test_empty_command(self):
        assert hook._is_readonly_bash("") is True

    def test_unknown_command_not_readonly(self):
        assert hook._is_readonly_bash("my-custom-script.sh") is False

    def test_semicolon_separator(self):
        assert hook._is_readonly_bash("ls; cat foo") is True

    def test_or_separator(self):
        assert hook._is_readonly_bash("cat foo || echo fallback") is True

    def test_echo_is_readonly(self):
        assert hook._is_readonly_bash("echo hello") is True

    def test_python_is_readonly(self):
        assert hook._is_readonly_bash("python3 --version") is True


# ── _is_project_file ──


class TestIsProjectFile:
    def test_file_inside_project(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        filepath = os.path.join(project, "src", "main.py")
        assert hook._is_project_file(filepath, project) is True

    def test_file_is_project_root(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        assert hook._is_project_file(project, project) is True

    def test_file_outside_project(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        assert hook._is_project_file("/etc/passwd", project) is False

    def test_empty_path(self):
        assert hook._is_project_file("", "/home/user") is False

    def test_empty_project(self):
        assert hook._is_project_file("/home/user/file.py", "") is False

    def test_path_traversal(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        outside = os.path.join(project, "..", "secret.txt")
        assert hook._is_project_file(outside, project) is False


# ── check_auto_allow ──


class TestCheckAutoAllow:
    def test_matching_pattern(self, tmp_settings_file):
        settings = tmp_settings_file(["Bash(git commit:*)"])
        assert hook.check_auto_allow("Bash", "git commit -m 'test'", settings) is True

    def test_no_matching_pattern(self, tmp_settings_file):
        settings = tmp_settings_file(["Bash(git commit:*)"])
        assert hook.check_auto_allow("Bash", "rm -rf /", settings) is False

    def test_blanket_tool_allow(self, tmp_settings_file):
        settings = tmp_settings_file(["Read"])
        assert hook.check_auto_allow("Read", "/any/path", settings) is True

    def test_missing_settings_file(self):
        assert hook.check_auto_allow("Read", "x", "/nonexistent/settings.json") is False

    def test_empty_allow_list(self, tmp_settings_file):
        settings = tmp_settings_file([])
        assert hook.check_auto_allow("Read", "x", settings) is False

    def test_compound_bash_all_allowed(self, tmp_settings_file):
        settings = tmp_settings_file(["Bash(git:*)", "Bash(echo:*)"])
        assert hook.check_auto_allow("Bash", "git status && echo done", settings) is True

    def test_compound_bash_partial_not_allowed(self, tmp_settings_file):
        settings = tmp_settings_file(["Bash(git:*)"])
        assert hook.check_auto_allow("Bash", "git status && rm foo", settings) is False

    def test_write_path_pattern(self, tmp_settings_file):
        settings = tmp_settings_file(["Write(/home/user/proj/*)"])
        assert hook.check_auto_allow("Write", "/home/user/proj/src/main.py", settings) is True

    def test_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        assert hook.check_auto_allow("Read", "x", str(bad)) is False


# ── check_smart_auto_approve ──


class TestCheckSmartAutoApprove:
    def test_readonly_tool(self):
        assert hook.check_smart_auto_approve("Read", {}, "/any") is True
        assert hook.check_smart_auto_approve("Glob", {}, "/any") is True
        assert hook.check_smart_auto_approve("Grep", {}, "/any") is True

    def test_readonly_bash(self):
        assert hook.check_smart_auto_approve("Bash", {"command": "ls -la"}, "/any") is True

    def test_dangerous_bash(self):
        assert hook.check_smart_auto_approve("Bash", {"command": "rm foo"}, "/any") is False

    def test_write_inside_project(self, tmp_path):
        project = str(tmp_path)
        filepath = os.path.join(project, "src", "main.py")
        assert hook.check_smart_auto_approve("Write", {"file_path": filepath}, project) is True

    def test_write_outside_project(self, tmp_path):
        project = str(tmp_path)
        assert hook.check_smart_auto_approve("Write", {"file_path": "/etc/passwd"}, project) is False

    def test_edit_inside_project(self, tmp_path):
        project = str(tmp_path)
        filepath = os.path.join(project, "foo.py")
        assert hook.check_smart_auto_approve("Edit", {"file_path": filepath}, project) is True

    def test_unknown_tool(self):
        assert hook.check_smart_auto_approve("CustomTool", {}, "/any") is False

    def test_bash_empty_command(self):
        assert hook.check_smart_auto_approve("Bash", {"command": ""}, "/any") is False

    def test_bash_string_input(self):
        assert hook.check_smart_auto_approve("Bash", "not a dict", "/any") is False
