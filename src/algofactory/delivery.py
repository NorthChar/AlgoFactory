"""Read-only release checks. Findings identify locations, never matching secret bytes."""

import csv
import gzip
import hashlib
import json
import re
import subprocess

TOKEN_PATTERNS = (
    rb"gh[pousr]_[A-Za-z0-9]{36,}",
    rb"github_pat_[A-Za-z0-9_]{70,}",
    rb"sk-(?:proj-)?[A-Za-z0-9_-]{40,}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)


def contains_secret(data, secrets=()):
    return any(secret and secret in data for secret in secrets) or any(
        re.search(pattern, data) for pattern in TOKEN_PATTERNS
    )


def safe_file(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("release_path_escape")
    return path


def scan_history(root, secrets=()):
    """Scan every reachable blob through a streaming cat-file process, with bounded output."""
    names = subprocess.check_output(
        ["git", "rev-list", "--objects", "--all"], cwd=root
    ).splitlines()
    objects = [row.split(b" ", 1)[0] for row in names]
    checked = 0
    findings = []
    with subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    ) as process:
        for object_id in objects:
            process.stdin.write(object_id + b"\n")
            process.stdin.flush()
            fields = process.stdout.readline().split()
            if len(fields) != 3:
                raise ValueError("invalid_git_object_response")
            data = process.stdout.read(int(fields[2]))
            assert process.stdout.read(1) == b"\n"
            if fields[1] != b"blob":
                continue
            checked += 1
            if contains_secret(data, secrets):
                findings.append({"object": object_id.decode(), "rule": "potential_secret"})
            # Prediction archives contain structured model output, but inspect compressed text too.
            if data[:2] == b"\x1f\x8b":
                if contains_secret(gzip.decompress(data), secrets):
                    findings.append(
                        {"object": object_id.decode(), "rule": "compressed_potential_secret"}
                    )
        process.stdin.close()
        assert process.wait() == 0
    return {"blobs_scanned": checked, "findings": findings}


def archive_integrity(root):
    results = []
    for path in sorted((root / "examples").glob("*/verification.json")):
        record = json.loads(path.read_text())
        verified = 0
        for relative, expected in record.get("artifacts_sha256", {}).items():
            artifact = safe_file(path.parent, relative)
            if not artifact.is_file():
                raise ValueError("missing_archive_artifact:" + str(artifact.relative_to(root)))
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
                raise ValueError("archive_hash_mismatch:" + str(artifact.relative_to(root)))
            verified += 1
        results.append(
            {
                "manifest": str(path.relative_to(root)),
                "artifacts_checked": verified,
                "historical_status": record.get("status", "see_original_record"),
            }
        )
    return results


def audit_release(root, *, secrets=(), history=False):
    root = root.resolve()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    findings = []
    inventory = {}
    link_count = 0
    for name in filter(None, tracked):
        path = safe_file(root, name)
        if not path.is_file():
            findings.append({"path": name, "rule": "missing_tracked_file"})
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append({"path": name, "rule": "private_environment_file"})
        data = path.read_bytes()
        if len(data) >= 100_000_000:
            findings.append({"path": name, "rule": "file_exceeds_github_100mb"})
        if contains_secret(data, secrets) or (
            path.suffix == ".gz" and contains_secret(gzip.decompress(data), secrets)
        ):
            findings.append({"path": name, "rule": "potential_secret"})
        inventory[name] = hashlib.sha256(data).hexdigest()
        if path.suffix == ".md" and (name == "README.md" or name.startswith("docs/")):
            for link in re.findall(r"\]\(([^)]+)\)", data.decode()):
                if "://" in link or link.startswith(("#", "mailto:")):
                    continue
                target = (path.parent / link.split("#")[0]).resolve()
                if not target.is_relative_to(root) or not target.exists():
                    findings.append({"path": name, "rule": "broken_local_link", "target": link})
                link_count += 1
    with (root / "docs/requirements-matrix.csv").open(newline="") as handle:
        rows = list(csv.reader(handle))
    table = [
        line
        for line in (root / "docs/requirements-matrix.md").read_text().splitlines()
        if line.startswith("|")
    ][2:]
    assert len(rows) - 1 == len(table), "matrix_row_count"
    assert all(
        row == [part.strip() for part in line.strip("|").split("|")]
        for row, line in zip(rows[1:], table, strict=True)
    ), "matrix_content_mismatch"
    identifiers = [row[0] for row in rows[1:]]
    assert len(identifiers) == len(set(identifiers)), "duplicate_requirement_id"
    assert {f"B{i:02}" for i in range(1, 12)} | {f"R{i:02}" for i in range(1, 11)} <= set(
        identifiers
    )
    readme = (root / "README.md").read_text()
    assert all(re.search(rf"^## {i}\. ", readme, re.M) for i in range(1, 11)), "readme_ten_sections"
    original = json.loads((root / "docs/source/sha256.json").read_text())
    assert all(
        hashlib.sha256((root / "docs/source" / name).read_bytes()).hexdigest() == digest
        for name, digest in original.items()
    ), "source_archive_changed"
    archives = archive_integrity(root)
    historical = scan_history(root, secrets) if history else None
    if historical:
        findings.extend(historical["findings"])
    return {
        "status": "failed" if findings else "passed",
        "findings": findings,
        "tracked_files": len(inventory),
        "tracked_sha256": inventory,
        "local_links_checked": link_count,
        "requirements": len(rows) - 1,
        "source_archive_intact": True,
        "readme_sections": 10,
        "archive_integrity": archives,
        "history": historical,
        "credential_check_scope": "exact supplied current secrets plus high-confidence token/private-key patterns; not a guarantee against all possible secrets",
    }
