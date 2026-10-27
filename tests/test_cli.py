import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "algofactory.cli", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_ingest_search_export_import(tmp_path):
    db = tmp_path / "db.sqlite"
    result = cli("ingest", "data/customer_churn.txt", "--mode", "mock", "--db", db)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["inserted"]["entities"] == 6
    result = cli("search", "--db", db, "--text", "Logistic", "--task-type", "binary_classification")
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)["results"][0]
    assert evidence["record"]["name"] == "Logistic Regression"
    result = cli("show", evidence["record"]["id"], "--db", db)
    assert result.returncode == 0
    out = tmp_path / "export"
    result = cli("export", "--db", db, "--output-dir", out)
    assert result.returncode == 0, result.stderr
    assert (out / "knowledge.graphml").is_file()
    result = cli("import", out / "knowledge.json", "--db", tmp_path / "restored.sqlite")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["inserted"]["relations"] == 7


def test_cli_errors_nonzero_and_machine_readable(tmp_path):
    result = cli("search", "--db", tmp_path / "missing.sqlite")
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "failed"
    assert not (tmp_path / "missing.sqlite").exists()
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALGOFACTORY_API_")}
    result = cli(
        "ingest", "data/customer_churn.txt", "--mode", "api", "--db", tmp_path / "db", env=env
    )
    assert result.returncode == 1
    assert json.loads(result.stderr)["error"] == "api_configuration_missing"


def test_cli_schema_export_and_truthful_status(tmp_path):
    result = cli("schemas", "--output-dir", tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(list(tmp_path.glob("*.json"))) == 8
    assert "TaskSpec" in json.loads(result.stdout)["schemas"]
    result = cli("status")
    assert json.loads(result.stdout)["phase"] == 1
    assert json.loads(result.stdout)["core_workflow"] == "not_implemented"
