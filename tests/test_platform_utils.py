"""Tests for platform_utils.py — path encoding, directory helpers, process checks."""

import os
import sys
import unittest.mock as mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import platform_utils


class TestEncodeProjectPath:
    def test_linux_absolute_path(self):
        assert platform_utils.encode_project_path("/home/user/proj") == "-home-user-proj"

    def test_linux_root(self):
        assert platform_utils.encode_project_path("/") == "-"

    def test_linux_nested_path(self):
        assert platform_utils.encode_project_path("/home/user/a/b/c") == "-home-user-a-b-c"

    def test_path_without_leading_slash(self):
        result = platform_utils.encode_project_path("relative/path")
        assert result.startswith("-")
        assert result == "-relative-path"

    def test_single_component(self):
        assert platform_utils.encode_project_path("/myproject") == "-myproject"

    @mock.patch.object(platform_utils, "IS_WINDOWS", True)
    def test_windows_path(self):
        assert platform_utils.encode_project_path("C:\\Users\\foo\\proj") == "-C-Users-foo-proj"

    @mock.patch.object(platform_utils, "IS_WINDOWS", True)
    def test_windows_forward_slash(self):
        assert platform_utils.encode_project_path("C:/Users/foo/proj") == "-C-Users-foo-proj"


class TestGetQueueDir:
    def test_unix_returns_tmp(self):
        with mock.patch.object(platform_utils, "IS_WINDOWS", False):
            assert platform_utils.get_queue_dir() == "/tmp/claude-webui"

    def test_windows_uses_tempdir(self):
        with mock.patch.object(platform_utils, "IS_WINDOWS", True):
            result = platform_utils.get_queue_dir()
            assert result.endswith("claude-webui")


class TestGetImageDir:
    def test_unix_returns_tmp(self):
        with mock.patch.object(platform_utils, "IS_WINDOWS", False):
            assert platform_utils.get_image_dir() == "/tmp/claude-images"

    def test_windows_uses_tempdir(self):
        with mock.patch.object(platform_utils, "IS_WINDOWS", True):
            result = platform_utils.get_image_dir()
            assert result.endswith("claude-images")


class TestIsProcessAlive:
    def test_current_process_is_alive(self):
        assert platform_utils.is_process_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        # PID 99999999 is extremely unlikely to exist
        assert platform_utils.is_process_alive(99999999) is False

    def test_parent_process_is_alive(self):
        # Parent process should be alive
        assert platform_utils.is_process_alive(os.getppid()) is True
