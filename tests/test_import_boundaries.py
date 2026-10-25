import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_import_linter_contracts_pass():
    proc = subprocess.run(
        ["lint-imports", "--config", "pyproject.toml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
