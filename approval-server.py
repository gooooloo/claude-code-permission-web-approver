#!/usr/bin/env python3
"""
Claude Code Permission Approval Web Server

Watches /tmp/claude-approvals/ for permission requests from the hook script,
serves a web UI for the user to approve/deny, and writes responses back.

Usage: python3 approval-server.py
Then open http://localhost:19836
"""

import json
import glob
import os
import signal
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

QUEUE_DIR = "/tmp/claude-approvals"
PORT = 19836

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Code Approvals</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: #1a1a2e;
    color: #e0e0e0;
    min-height: 100vh;
    padding: 24px;
  }
  h1 {
    font-size: 20px;
    color: #a78bfa;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .status {
    font-size: 12px;
    color: #666;
    margin-left: auto;
    font-weight: normal;
  }
  .empty {
    text-align: center;
    color: #555;
    margin-top: 80px;
    font-size: 16px;
  }
  .empty .dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #4ade80;
    border-radius: 50%;
    margin-right: 8px;
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 1; }
  }
  .card {
    background: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    animation: slideIn 0.3s ease;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }
  .tool-badge {
    background: #a78bfa22;
    color: #a78bfa;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
  }
  .project-tag {
    background: #facc1522;
    color: #facc15;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
  }
  .session-id {
    color: #666;
    font-size: 11px;
  }
  .project-path {
    font-size: 11px;
    color: #555;
    margin-bottom: 8px;
    font-weight: 600;
  }
  .timestamp {
    font-size: 11px;
    color: #555;
    margin-left: auto;
  }
  .detail {
    background: #0f0f23;
    border-radius: 8px;
    padding: 14px;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-all;
    margin-bottom: 14px;
    max-height: 300px;
    overflow-y: auto;
  }
  .allow-info {
    font-size: 12px;
    color: #888;
    margin-bottom: 14px;
  }
  .allow-info code {
    color: #facc15;
    background: #facc1511;
    padding: 2px 6px;
    border-radius: 4px;
  }
  .buttons {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }
  button {
    padding: 8px 20px;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  button:active { transform: scale(0.97); }
  .btn-allow {
    background: #3b82f6;
    color: white;
  }
  .btn-allow:hover { background: #2563eb; }
  .btn-always {
    background: #16a34a;
    color: white;
  }
  .btn-always:hover { background: #15803d; }
  .btn-deny {
    background: #333;
    color: #ccc;
  }
  .btn-deny:hover { background: #ef4444; color: white; }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
</head>
<body>
<h1>
  Claude Code Approvals
  <span class="status" id="status">Connected</span>
</h1>
<div id="requests"></div>

<script>
let knownIds = new Set();
let respondedIds = new Set();

async function fetchPending() {
  try {
    const res = await fetch('/api/pending');
    const data = await res.json();
    document.getElementById('status').textContent =
      'Last checked: ' + new Date().toLocaleTimeString();
    renderRequests(data.requests.filter(r => !respondedIds.has(r.id)));
  } catch (e) {
    document.getElementById('status').textContent = 'Connection error';
  }
}

function renderRequests(requests) {
  const container = document.getElementById('requests');
  if (requests.length === 0) {
    container.innerHTML = '<div class="empty"><span class="dot"></span>Waiting for permission requests...</div>';
    knownIds.clear();
    return;
  }
  // Remove cards for requests that no longer exist
  const currentIds = new Set(requests.map(r => r.id));
  knownIds.forEach(id => {
    if (!currentIds.has(id)) {
      const el = document.getElementById('card-' + id);
      if (el) el.remove();
    }
  });
  // Add new cards
  requests.forEach(req => {
    if (!knownIds.has(req.id)) {
      const card = document.createElement('div');
      card.className = 'card';
      card.id = 'card-' + req.id;
      const time = new Date(req.timestamp * 1000).toLocaleTimeString();
      card.innerHTML = `
        <div class="card-header">
          <span class="tool-badge">${esc(req.tool_name)}</span>
          <span class="project-tag">${esc(req.project_dir || '').split('/').pop()}</span>
          <span class="session-id">Session ${req.session_id || '?'}</span>
          <span class="timestamp">${time}</span>
        </div>
        <div class="project-path">${esc(req.project_dir || '')}</div>
        <div class="detail">${esc(req.detail)}</div>
        ${req.detail_sub ? '<div class="detail" style="margin-top:8px;color:#aaa;font-size:12px">' + esc(req.detail_sub) + '</div>' : ''}
        <div class="allow-info">"Always Allow" will apply to: <code>${esc(req.allow_pattern)}</code></div>
        <div class="buttons">
          <button class="btn-deny" onclick="respond('${req.id}','deny',this)">Deny</button>
          <button class="btn-always" onclick="respond('${req.id}','always',this)">Always Allow</button>
          <button class="btn-allow" onclick="respond('${req.id}','allow',this)">Allow</button>
        </div>`;
      container.prepend(card);
    }
  });
  knownIds = currentIds;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function respond(id, decision, btn) {
  const card = document.getElementById('card-' + id);
  const buttons = card.querySelectorAll('button');
  buttons.forEach(b => b.disabled = true);
  btn.textContent = '...';

  try {
    await fetch('/api/respond', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id, decision})
    });
    respondedIds.add(id);
    knownIds.delete(id);
    card.remove();
  } catch (e) {
    buttons.forEach(b => b.disabled = false);
    btn.textContent = 'Error';
  }
}

fetchPending();
setInterval(fetchPending, 500);
</script>
</body>
</html>"""


def _is_pid_alive(pid):
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class ApprovalHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default logging
        pass

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        elif self.path == "/api/pending":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            requests = []
            for path in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.request.json"))):
                try:
                    with open(path) as f:
                        data = json.load(f)
                    # Skip if response already exists
                    resp_path = path.replace(".request.json", ".response.json")
                    if os.path.exists(resp_path):
                        continue
                    # Skip and cleanup if hook process is dead
                    pid = data.get("pid")
                    if pid and not _is_pid_alive(pid):
                        os.remove(path)
                        continue
                    requests.append(data)
                except (json.JSONDecodeError, IOError):
                    continue
            self.wfile.write(json.dumps({"requests": requests}).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/respond":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            request_id = body.get("id", "")
            decision = body.get("decision", "deny")

            # Validate request exists
            request_file = os.path.join(QUEUE_DIR, f"{request_id}.request.json")
            if not os.path.exists(request_file):
                self.send_error(404, "Request not found")
                return

            # If "always", write to settings.local.json
            if decision == "always":
                try:
                    with open(request_file) as f:
                        req_data = json.load(f)
                    settings_file = req_data.get("settings_file", "")
                    allow_pattern = req_data.get("allow_pattern", "")
                    if settings_file and allow_pattern:
                        self._add_to_settings(settings_file, allow_pattern)
                except (json.JSONDecodeError, IOError):
                    pass

            # Write response file
            response_file = os.path.join(QUEUE_DIR, f"{request_id}.response.json")
            with open(response_file, "w") as f:
                json.dump({"decision": decision}, f)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        else:
            self.send_error(404)

    def _add_to_settings(self, settings_file, pattern):
        """Add an allow pattern to settings.local.json"""
        try:
            if os.path.exists(settings_file):
                with open(settings_file) as f:
                    settings = json.load(f)
            else:
                settings = {"permissions": {"allow": []}}

            if "permissions" not in settings:
                settings["permissions"] = {"allow": []}
            if "allow" not in settings["permissions"]:
                settings["permissions"]["allow"] = []

            if pattern not in settings["permissions"]["allow"]:
                settings["permissions"]["allow"].append(pattern)
                with open(settings_file, "w") as f:
                    json.dump(settings, f, indent=2)
                    f.write("\n")
                print(f"[+] Added to allowlist: {pattern}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"[!] Failed to update settings: {e}")


def main():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), ApprovalHandler)
    print(f"Claude Code Approval Server running on http://localhost:{PORT}")
    print(f"Watching: {QUEUE_DIR}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
