#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PROBE="src/taryx/core/_boundary_violation_probe.py"
cleanup() { rm -f "$PROBE"; }
trap cleanup EXIT

uv run lint-imports

printf '"""Deliberate violation: must be rejected by Import Linter."""\nfrom taryx.interfaces import tasks  # noqa: F401\n' > "$PROBE"
if uv run lint-imports; then
    echo "ERROR: Import Linter accepted a deliberate core -> interfaces violation" >&2
    exit 1
fi
echo "OK: deliberate core -> interfaces violation was rejected."
