"""Shared fixtures for claude-code-webui tests."""

import importlib
import os
import sys
import json
import tempfile

import pytest

# Add project root to sys.path so modules can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def tmp_queue_dir(tmp_path):
    """Provide a temporary queue directory."""
    queue = tmp_path / "claude-webui"
    queue.mkdir()
    return str(queue)


@pytest.fixture
def tmp_settings_file(tmp_path):
    """Provide a temporary settings.local.json file."""
    settings_path = tmp_path / ".claude" / "settings.local.json"
    settings_path.parent.mkdir(parents=True)

    def _write(allow_patterns):
        data = {"permissions": {"allow": allow_patterns}}
        settings_path.write_text(json.dumps(data))
        return str(settings_path)

    return _write


def import_hook_module(name):
    """Import a hook module with hyphens in filename using importlib."""
    path = os.path.join(PROJECT_ROOT, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
