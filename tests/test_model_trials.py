import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from algofactory.datasets import write_json
from algofactory.web import models

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "examples/api-phase3/comparison"
VERSION = "candidates/text_logistic/attempt-1"


@pytest.fixture
def model_root(tmp_path):
    if not (ROOT / "runtime/banking77-data/manifest.json").exists():
        pytest.skip("local imported dataset required")
    shutil.copytree(ROOT / "runtime/banking77-data", tmp_path / "runtime/banking77-data")
    shutil.copytree(ROOT / RELATIVE, tmp_path / RELATIVE)
    return tmp_path


def test_input_guard_rejects_test_duplicates_and_invalid_input(model_root):
    for text in ["", " ", "123", "中文咨询", "a" * 1001]:
        with pytest.raises(ValueError):
            models.checked_text(model_root, text)
    text = pd.read_csv(model_root / "runtime/banking77-data/test_features.csv").text.iloc[0]
    with pytest.raises(ValueError, match="frozen_test"):
        models.checked_text(model_root, "  " + text.upper() + "  ")
    assert models.checked_text(model_root, "A newly written banking question today.")


def test_model_provenance_and_no_silent_fallback(model_root):
    directory, dataset, manifest, report = models.source_version(model_root, RELATIVE, VERSION)
    location = models.prepared_directory(model_root, RELATIVE, VERSION)
    location.mkdir(parents=True)
    blob = location / "model.pkl.gz"
    blob.write_bytes(b"opaque model, never deserialize on host")
    from algofactory.datasets import sha256_file

    metadata = {
        "model_sha256": sha256_file(blob),
        "code_hash": report["code_hash"],
        "train_sha256": manifest["files"]["train.csv"],
        "training_rows": 7993,
        "classes": manifest["class_labels"],
        "image_id": "approved",
        "environment": {"python": "test"},
        "config": {k: manifest[k] for k in ("data_fingerprint", "split_id", "class_names")},
    }
    write_json(location / "model-provenance.json", metadata)
    engine = SimpleNamespace(approval={"image_id": "approved"})
    assert models.checked_model(model_root, RELATIVE, VERSION, engine)[0] == blob
    for key, value in [
        ("code_hash", "changed"),
        ("training_rows", 42),
        ("classes", [0]),
        ("image_id", "different"),
        ("model_sha256", "wrong"),
    ]:
        write_json(location / "model-provenance.json", metadata | {key: value})
        with pytest.raises(ValueError, match="provenance"):
            models.checked_model(model_root, RELATIVE, VERSION, engine)
    write_json(location / "model-provenance.json", metadata)
    blob.unlink()
    with pytest.raises(FileNotFoundError):
        models.checked_model(model_root, RELATIVE, VERSION, engine)
    with pytest.raises(ValueError, match="validated"):
        models.source_version(model_root, RELATIVE, "candidates/text_logistic/attempt-0")


def test_predict_fail_closed_on_worker_or_invalid_probabilities(model_root, monkeypatch):
    from algofactory.workflow_models import WorkerResult, WorkflowFailure

    _, _, manifest, _ = models.source_version(model_root, RELATIVE, VERSION)
    monkeypatch.setattr(
        models, "checked_model", lambda *a: (Path("unused"), {"environment": {}}, "test")
    )

    class Engine:
        def execute(self, *args, **kwargs):
            assert args[1] is None
            assert args[3]["stage"] == "predict"
            assert args[5].timeout_seconds == 30
            raise WorkflowFailure("execution_timeout")

    monkeypatch.setattr(models, "executor", lambda *a: Engine())
    with pytest.raises(WorkflowFailure, match="timeout"):
        models.predict_text(model_root, RELATIVE, VERSION, "My newly written banking question.")
    monkeypatch.setattr(
        Engine,
        "execute",
        lambda *a, **k: WorkerResult(
            status="ok", row_ids=[0], classes=manifest["class_labels"], probabilities=[[0.0] * 77]
        ),
    )
    with pytest.raises(ValueError, match="probabilities"):
        models.predict_text(model_root, RELATIVE, VERSION, "My newly written banking question.")


def test_trial_picker_defaults_to_latest_validated_run(model_root, monkeypatch):
    import os

    from streamlit.testing.v1 import AppTest

    for identifier, timestamp in [("a" * 32, 1000), ("b" * 32, 2000)]:
        destination = model_root / "runtime/web-jobs" / identifier
        shutil.copytree(model_root / RELATIVE, destination / "run")
        write_json(destination / "state.json", {"status": "validated"})
        os.utime(destination / "run/report.json", (timestamp, timestamp))
    # Historical archive must be older to make the deterministic fixture explicit.
    os.utime(model_root / RELATIVE / "report.json", (500, 500))
    monkeypatch.setenv("ALGOFACTORY_PROJECT_ROOT", str(model_root))
    app = AppTest.from_file(ROOT / "src/algofactory/web/app.py", default_timeout=30).run()
    assert not app.exception
    choice = next(s for s in app.selectbox if s.label == "选择算法来源")
    assert choice.value == "runtime/web-jobs/" + "b" * 32 + "/run"
    assert any("本地任务" in label for label in choice.options)
    versions = next(s for s in app.selectbox if s.label == "选择通过验证的版本")
    assert "逻辑回归 · 修复版 1" in versions.options
