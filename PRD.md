# PRD: Claude Code Permission Web Approver

## Overview

A web-based approval UI for Claude Code permission hooks. Provides a browser interface to approve/deny tool execution requests from Claude Code, replacing the default terminal prompts.

## Goals

- Provide a user-friendly web UI for reviewing and approving Claude Code permission requests
- Support session-level auto-allow for trusted operations
- Enable remote approval workflows (e.g., from a phone or another device)

## Current Features

- Web-based approval/deny interface with request details
- Session-level auto-allow with multi-select support (server-side evaluation)
- AskUserQuestion support with custom text input
- Auto-cleanup of stale requests
- Prompt submission from Web UI when Claude Code is idle (via stop hook)
- Claude's last response displayed in prompt-waiting card
- "Allow Path" button for Write/Edit tools with hierarchical directory selection
- Split "Always Allow" for compound Bash commands (pipes and &&)
- Image upload support in Web UI prompt area
- WebFetch/WebSearch permission handling
- Mobile-optimized layout (buttons, spacing, detail height)

## TODO

- [ ] *(on hold)* **Add "Clear Context and Edit" shortcut (Shift+Tab) to ExitPlanMode card**
  - When an ExitPlanMode approval card is shown in the Web UI, add a keyboard shortcut (Shift+Tab) or button that triggers the "Clear context and edit" action.
  - This mirrors the Shift+Tab behavior available in the Claude Code CLI terminal.
  - Allows the user to clear the current context and re-edit the plan directly from the Web UI without switching back to the terminal.
- [ ] *(on hold)* **Add TODO management in Web UI independent of Claude Code session**
  - Problem: Currently adding TODOs to PRD.md requires going through Claude Code, which means the user cannot add new ideas while Claude is busy working on a task.
  - Add a TODO management section in the Web UI where users can add, view, and reorder TODO items at any time, regardless of whether Claude Code is idle or busy.
  - Possible approaches:
    - Web UI directly edits PRD.md (append new TODOs to the file) without involving Claude Code
    - A separate TODO storage (e.g., a JSON file) that Claude reads when starting a new task
    - A dedicated API endpoint on the approval server for CRUD operations on TODOs
  - The key requirement is decoupling: adding a TODO should never block on or interfere with an in-progress Claude Code session.
