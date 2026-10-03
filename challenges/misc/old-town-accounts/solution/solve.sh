#!/usr/bin/env bash
set -euo pipefail

here=$(dirname "$0")
python3 "$here/test-pool.py"
exec python3 "$here/solve.py" night
