"""Verify full, subset and single-intent workbench jobs in real Docker, with Mock only."""

import argparse
import time
import uuid
from pathlib import Path

from algofactory.datasets import sha256_file, write_json
from algofactory.experiments import ExperimentConfig
from algofactory.requirement_understanding import configuration_request
from algofactory.web.models import predict_text, selected_trial_version
from algofactory.web.service import Jobs, RunSettings, read_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--final-test",
        action="store_true",
        help="Evaluate derived tasks once; full task stays validation-only",
    )
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {"status": "running", "paid_api_calls": 0, "cases": []}
    write_json(out / "verification.json", summary)
    cases = [
        ("full", ExperimentConfig(algorithms=["text_logistic"])),
        (
            "subset-three",
            ExperimentConfig(
                goal="subset", intents=["card_arrival", "lost_or_stolen_card", "pending_transfer"]
            ),
        ),
        (
            "subset-two",
            ExperimentConfig(
                goal="subset",
                intents=["card_arrival", "lost_or_stolen_card"],
                algorithms=["text_logistic"],
            ),
        ),
        (
            "single-recall",
            ExperimentConfig(
                goal="one_vs_rest", intents=["lost_or_stolen_card"], objective="recall"
            ),
        ),
    ]
    jobs = Jobs(ROOT)
    try:
        for name, config in cases:
            values = dict(
                experiment=config,
                request=configuration_request(config),
                compare=len(config.algorithms) == 2,
                validation_only=not (args.final_test and config.goal != "full"),
                max_repairs=1,
            )
            draft = RunSettings.model_construct(**values)
            settings = RunSettings(**values, requirement_confirmation=draft.confirmation_digest())
            identifier = uuid.uuid4().hex
            jobs.submit(settings, identifier)
            started = time.monotonic()
            while True:
                state = read_json(jobs.path(identifier) / "state.json")
                if state["status"] not in {"queued", "running"}:
                    break
                if time.monotonic() - started > 300:
                    jobs.cancel(identifier)
                    raise RuntimeError("verification_job_timeout")
                time.sleep(0.5)
            relative = f"runtime/web-jobs/{identifier}/run"
            report = read_json(ROOT / relative / "report.json")
            item = {
                "name": name,
                "job": identifier,
                "report": relative + "/report.json",
                "status": state["status"],
                "error": state.get("error_category"),
                "configuration": config.frozen(),
                "test_attempted": report["test_attempted"],
                "validation": report.get("validation"),
                "persisted": report["persisted"],
            }
            summary["cases"].append(item)
            write_json(out / "verification.json", summary)
            assert state["status"] in {"validated", "accepted"}, state
            manifest = read_json(ROOT / relative / "data-manifest.json")
            config.validate_manifest(manifest)
            assert report["experiment_hash"] == config.digest and report["persisted"]
            assert report["test_attempted"] == (args.final_test and config.goal != "full")
            version = selected_trial_version(ROOT, relative)
            assert version is not None
            trial = predict_text(
                ROOT,
                relative,
                version,
                "My bank card has gone missing during today's trip, and I need assistance.",
            )
            item["trial"] = trial
            item["class_names"] = manifest["class_names"]
            item["split_counts"] = {s: len(ids) for s, ids in manifest["split_indices"].items()}
            print(name + ": " + state["status"] + ", trial passed", flush=True)
        summary["status"] = "passed"
    except Exception:
        summary["status"] = "failed"
        raise
    finally:
        summary["source_sha256"] = {
            str(p.relative_to(ROOT)): sha256_file(p) for p in sorted((ROOT / "src").rglob("*.py"))
        }
        write_json(out / "verification.json", summary)


if __name__ == "__main__":
    main()
