#!/usr/bin/env bash
# Lesson 1: overflow the name into the adjacent carrot count.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30004}"
python3 solution/exploit.py "$host" "$port" 1
