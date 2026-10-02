#!/usr/bin/env bash
# Lesson 4: use printf's %n conversion to write the target value.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30004}"
python3 solution/exploit.py "$host" "$port" 4
