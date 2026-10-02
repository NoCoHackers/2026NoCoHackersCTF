#!/usr/bin/env bash
# Lesson 2: replace the note's function pointer with secret_delivery.
set -euo pipefail
read -r host port <<<"${TARGET:-127.0.0.1 30004}"
python3 solution/exploit.py "$host" "$port" 2
