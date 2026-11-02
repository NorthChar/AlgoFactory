import shutil
from pathlib import Path

import pytest

from algofactory.web.data_view import dataset_snapshot, samples, validation_errors

ROOT = Path(__file__).resolve().parents[1]


def test_actual_readonly_data_and_archived_errors(monkeypatch):
    if not (ROOT / "runtime/banking77-data/manifest.json").exists():
        pytest.skip("local imported dataset required")
    original = Path.open

    def guard(path, *args, **kwargs):
        assert path.name not in {"test_features.csv", "test_labels.csv", "all_rows.csv"}
        assert not any(c in (args[0] if args else kwargs.get("mode", "r")) for c in "wa+")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    _, manifest, audit = dataset_snapshot(ROOT)
    assert audit["split_counts"] == {"train": 7993, "validation": 1999, "test": 3080}
    assert len(samples(ROOT)) == 7993
    errors, accuracy = validation_errors(
        ROOT, "examples/banking-classification/comparison", "candidates/text_logistic/attempt-1"
    )
    assert len(errors) == 253
    assert accuracy == pytest.approx(0.8734367183591796)
    assert set(errors.row_id) <= set(manifest["split_indices"]["validation"])
    with pytest.raises(ValueError):
        samples(ROOT, "test")


def test_browse_rejects_symlink_and_modified_dataset(tmp_path):
    if not (ROOT / "runtime/banking77-data/manifest.json").exists():
        pytest.skip("local imported dataset required")
    dest = tmp_path / "runtime/banking77-data"
    shutil.copytree(ROOT / "runtime/banking77-data", dest)
    (dest / "train.csv").write_text("changed")
    with pytest.raises(ValueError, match="fingerprint"):
        samples(tmp_path)
    (dest / "train.csv").unlink()
    (dest / "train.csv").symlink_to(ROOT / "runtime/banking77-data/train.csv")
    with pytest.raises(ValueError, match="unsafe"):
        samples(tmp_path)
