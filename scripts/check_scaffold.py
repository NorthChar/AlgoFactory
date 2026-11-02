"""Check original requirements and delivery documents; this is not algorithm acceptance."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name, expected in json.loads((root / "docs/source/sha256.json").read_text()).items():
    actual = hashlib.sha256((root / "docs/source" / name).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Source archive changed: {name}")
for name in ["delivery", "requirements-matrix", "architecture", "acceptance-gates"]:
    if not (root / f"docs/{name}.md").is_file():
        raise SystemExit(f"Missing document: {name}")
result = subprocess.run(
    [sys.executable, "-m", "algofactory.cli", "status"],
    cwd=root,
    env=__import__("os").environ.copy() | {"PYTHONPATH": str(root / "src")},
    capture_output=True,
    text=True,
    check=True,
)
if json.loads(result.stdout)["core_workflow"] not in {
    "not_implemented",
    "implemented_docker_required",
}:
    raise SystemExit("Unexpected scaffold status")
print("PASS: source hashes, documents and scaffold CLI; no algorithm acceptance performed")
