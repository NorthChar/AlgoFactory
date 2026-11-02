"""Pinned BANKING77 import, deterministic hygiene, lineage and immutable data identity."""

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

import pandas as pd
from sklearn.model_selection import train_test_split

from algofactory.datasets import sha256_file, write_json
from algofactory.knowledge.store import canonical
from algofactory.workflow_models import WorkflowFailure

REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
BASE_URL = f"https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/{REVISION}"
SOURCE = {
    "repository": "https://github.com/PolyAI-LDN/task-specific-datasets",
    "revision": REVISION,
    "license": "CC-BY-4.0",
    "attribution": "PolyAI; Iñigo Casanueva, Tadas Temcinas, Daniela Gerz, Matthew Henderson, Ivan Vulić (2020), Efficient Intent Detection with Dual Sentence Encoders.",
    "paper": "https://arxiv.org/abs/2003.04807",
    "files": {
        "train.csv": {
            "url": BASE_URL + "/banking_data/train.csv",
            "sha256": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
        },
        "test.csv": {
            "url": BASE_URL + "/banking_data/test.csv",
            "sha256": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
        },
        "LICENSE": {
            "url": BASE_URL + "/LICENSE",
            "sha256": "7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661",
        },
    },
}
POLICY = {
    "version": "banking77-clean-v1",
    "normalization": "strip -> casefold -> collapse Unicode whitespace",
    "overlap": "remove training rows whose normalized text occurs in official test",
    "duplicates": "keep first training text+label; conflicting labels stop import",
    "test": "preserve all official test rows and order; disclose internal duplicates",
    "validation_fraction": 0.2,
    "seed": 42,
    "label_order": "lexicographic category names mapped to 0..76",
}


def normalize(text):
    return re.sub(r"\s+", " ", text.strip().casefold())


def clean_frames(train, test):
    """Pure hygiene step, also exercised with adversarial small fixtures."""
    train, test = train.copy(), test.copy()
    for frame in (train, test):
        if list(frame.columns) != ["text", "category"] or frame.empty:
            raise WorkflowFailure("banking_schema_mismatch")
        if any(not isinstance(v, str) or not v.strip() for v in frame.to_numpy().flat):
            raise WorkflowFailure("banking_invalid_text_or_label")
        frame["normalized"] = frame.text.map(normalize)
    combined = pd.concat([train, test], ignore_index=True)
    if (combined.groupby("normalized").category.nunique() > 1).any():
        raise WorkflowFailure("banking_conflicting_labels")
    train["source_row"] = range(len(train))
    test["source_row"] = range(len(test))
    overlap = train.normalized.isin(set(test.normalized))
    removed = [
        {"source_row": int(i), "reason": "official_test_overlap"}
        for i in train.loc[overlap, "source_row"]
    ]
    train = train.loc[~overlap].copy()
    duplicates = train.duplicated(["normalized", "category"])
    removed += [
        {"source_row": int(i), "reason": "training_duplicate"}
        for i in train.loc[duplicates, "source_row"]
    ]
    return train.loc[~duplicates].copy(), test, sorted(removed, key=lambda r: r["source_row"])


def prepared(raw):
    for name, info in SOURCE["files"].items():
        if sha256_file(raw / name) != info["sha256"]:
            raise WorkflowFailure("banking_raw_fingerprint_mismatch")
    train, test, removed = clean_frames(
        pd.read_csv(raw / "train.csv", keep_default_na=False),
        pd.read_csv(raw / "test.csv", keep_default_na=False),
    )
    classes = sorted(train.category.unique().tolist())
    if len(classes) != 77 or set(test.category) != set(classes):
        raise WorkflowFailure("banking_label_space_mismatch")
    mapping = {name: i for i, name in enumerate(classes)}
    combined = pd.concat(
        [train.assign(source_split="train"), test.assign(source_split="test")], ignore_index=True
    )
    combined.insert(0, "row_id", range(len(combined)))
    combined["intent"] = combined.category.map(mapping)
    training, validation = train_test_split(
        list(range(len(train))),
        test_size=0.2,
        random_state=42,
        stratify=train.category,
    )
    split = {
        "train": sorted(training),
        "validation": sorted(validation),
        "test": list(range(len(train), len(combined))),
    }
    all_rows = combined[["row_id", "text", "intent"]]
    frames = {"all_rows.csv": all_rows, "train.csv": all_rows.iloc[split["train"]]}
    for stage in ("validation", "test"):
        selected = all_rows.iloc[split[stage]]
        frames[stage + "_features.csv"] = selected[["row_id", "text"]]
        frames[stage + "_labels.csv"] = selected[["row_id", "intent"]]
    frames["lineage.csv"] = combined[["row_id", "source_split", "source_row"]]
    for ids in split.values():
        if set(all_rows.iloc[ids].intent) != set(range(77)):
            raise WorkflowFailure("banking_split_missing_class")
    audit = {
        "policy": POLICY,
        "removed_training_rows": removed,
        "official_train_rows": len(train) + len(removed),
        "clean_train_pool_rows": len(train),
        "official_test_rows": len(test),
        "official_test_duplicate_rows": test.loc[
            test.duplicated("normalized"), "source_row"
        ].tolist(),
        "split_counts": {k: len(v) for k, v in split.items()},
        "class_counts": {
            k: {
                str(c): int(n)
                for c, n in all_rows.iloc[v].intent.value_counts().sort_index().items()
            }
            for k, v in split.items()
        },
    }
    return frames, split, classes, audit


def select_frames(frames, split, classes, audit, selection):
    from algofactory.experiments import ExperimentConfig

    config = ExperimentConfig(**selection)
    if selection != config.selection():
        raise ValueError("noncanonical_dataset_selection")
    if config.goal == "full":
        raise ValueError("derived_selection_must_change_goal")
    base = frames["all_rows.csv"].copy()
    original_ids = {name: i for i, name in enumerate(classes)}
    if config.goal == "subset":
        base = base[base.intent.isin([original_ids[n] for n in config.intents])].copy()
        mapping = {original_ids[n]: i for i, n in enumerate(config.intents)}
        base["intent"] = base.intent.map(mapping)
        names = config.intents
    else:
        base["intent"] = (base.intent == original_ids[config.intents[0]]).astype(int)
        names = ["other_known_intents", config.intents[0]]
    kept = set(base.row_id)
    selected_split = {stage: [i for i in ids if i in kept] for stage, ids in split.items()}
    output = {
        "all_rows.csv": base,
        "lineage.csv": frames["lineage.csv"][frames["lineage.csv"].row_id.isin(kept)],
    }
    for stage, ids in selected_split.items():
        selected = base[base.row_id.isin(ids)]
        if set(selected.intent) != set(range(len(names))):
            raise WorkflowFailure("selected_split_missing_class")
        if stage == "train":
            output["train.csv"] = selected
        else:
            output[stage + "_features.csv"] = selected[["row_id", "text"]]
            output[stage + "_labels.csv"] = selected[["row_id", "intent"]]
    audit = {
        **audit,
        "selection": config.selection(),
        "parent_split_counts": audit["split_counts"],
        "split_counts": {stage: len(ids) for stage, ids in selected_split.items()},
        "class_counts": {
            stage: {
                str(k): int(v)
                for k, v in base[base.row_id.isin(ids)].intent.value_counts().sort_index().items()
            }
            for stage, ids in selected_split.items()
        },
        "split_policy": "preserve parent split membership and row IDs; filter/remap only",
        "negative_scope": "remaining 76 known BANKING77 intents, not arbitrary unknown text"
        if config.goal == "one_vs_rest"
        else None,
    }
    return output, selected_split, names, audit


def derive_banking77(source, destination, experiment):
    from algofactory.datasets import verify_dataset

    parent = verify_dataset(source)
    if parent.get("task_profile") != "banking77" or parent.get("selection"):
        raise ValueError("derivation_requires_full_banking77")
    return import_banking77(destination, source / "raw", selection=experiment.selection())


def import_banking77(directory: Path, raw_dir: Path | None = None, *, selection=None):
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Dataset destination must be empty; frozen data is never overwritten")
    raw = directory / "raw"
    raw.mkdir(parents=True)
    for name, info in SOURCE["files"].items():
        destination = raw / name
        if raw_dir is not None:
            shutil.copyfile(raw_dir / name, destination)
        else:
            with urlopen(info["url"], timeout=60) as response:
                destination.write_bytes(response.read(2_000_001))
        if sha256_file(destination) != info["sha256"]:
            raise WorkflowFailure("banking_raw_fingerprint_mismatch")
        destination.chmod(0o444)
    frames, split, classes, audit = prepared(raw)
    if selection is not None:
        frames, split, classes, audit = select_frames(frames, split, classes, audit, selection)
    for name, frame in frames.items():
        frame.to_csv(directory / name, index=False)
    write_json(directory / "audit.json", audit)
    write_json(directory / "labels.json", {str(i): name for i, name in enumerate(classes)})
    manifest = {
        "schema_version": 1,
        "task_profile": "banking77",
        "generator": POLICY["version"],
        "source": SOURCE,
        "imported_at": datetime.now(UTC).isoformat(),
        "importer_sha256": sha256_file(Path(__file__)),
        "policy": POLICY,
        "rows": len(frames["all_rows.csv"]),
        "seed": 42,
        "target": "intent",
        "numeric_features": [],
        "categorical_features": [],
        "text_features": ["text"],
        "class_names": classes,
        "class_labels": list(range(len(classes))),
        "split_indices": split,
        "split_id": "split:" + hashlib.sha256(canonical(split).encode()).hexdigest(),
        "data_fingerprint": sha256_file(directory / "all_rows.csv"),
        "files": {
            name: sha256_file(directory / name)
            for name in sorted([*frames, "audit.json", "labels.json"])
        },
    }
    if selection is not None:
        manifest["selection"] = selection
    write_json(directory / "manifest.json", manifest)
    return manifest


def verify_banking77(directory, manifest):
    if manifest["source"] != SOURCE or manifest["policy"] != POLICY:
        raise WorkflowFailure("banking_source_or_policy_mismatch")
    frames, split, classes, audit = prepared(directory / "raw")
    if "selection" in manifest:
        frames, split, classes, audit = select_frames(
            frames, split, classes, audit, manifest["selection"]
        )
    if (
        manifest["task_profile"] != "banking77"
        or manifest["target"] != "intent"
        or manifest["numeric_features"] != []
        or manifest["categorical_features"] != []
        or manifest["text_features"] != ["text"]
        or manifest["class_names"] != classes
        or manifest["class_labels"] != list(range(len(classes)))
        or manifest["seed"] != 42
        or manifest["rows"] != len(frames["all_rows.csv"])
        or manifest["split_indices"] != split
        or manifest["split_id"] != "split:" + hashlib.sha256(canonical(split).encode()).hexdigest()
        or manifest["data_fingerprint"] != sha256_file(directory / "all_rows.csv")
        or set(manifest["files"]) != {*frames, "audit.json", "labels.json"}
    ):
        raise WorkflowFailure("banking_manifest_mismatch")
    for name, expected in frames.items():
        # Reconstruct from pinned raw inputs: a rewritten manifest cannot conceal changed splits.
        digest = hashlib.sha256(expected.to_csv(index=False).encode()).hexdigest()
        if sha256_file(directory / name) != digest or manifest["files"][name] != digest:
            raise WorkflowFailure("banking_processed_data_mismatch")
    for name, expected in (
        ("audit.json", audit),
        ("labels.json", {str(i): v for i, v in enumerate(classes)}),
    ):
        if (
            json.loads((directory / name).read_text()) != expected
            or sha256_file(directory / name) != manifest["files"][name]
        ):
            raise WorkflowFailure("banking_metadata_mismatch")
    return manifest
