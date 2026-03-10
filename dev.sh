#!/bin/bash
cd "$(dirname "$0")"
ls *.py | entr -r python3 server.py "$@"
