#!/bin/bash
# Cleanup matching request files after tool execution
QUEUE_DIR="/tmp/claude-approvals"

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // {}' | jq -Sc '.')

for req_file in "$QUEUE_DIR"/*.request.json; do
  [ -f "$req_file" ] || continue
  REQ_NAME=$(jq -r '.tool_name // ""' "$req_file")
  REQ_INPUT=$(jq -Sc '.tool_input // {}' "$req_file")
  if [ "$REQ_NAME" = "$TOOL_NAME" ] && [ "$REQ_INPUT" = "$TOOL_INPUT" ]; then
    RESP_FILE="${req_file%.request.json}.response.json"
    rm -f "$req_file" "$RESP_FILE"
    break
  fi
done
