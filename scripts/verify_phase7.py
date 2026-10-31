"""Exercise Phase 7 CLI, real Web submission, archived errors and saved-model inference.

Run after importing BANKING77 and building the approved sandbox. No paid provider is used.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from algofactory.cli import parser, run
from algofactory.datasets import sha256_file, write_json
from algofactory.experiments import ExperimentConfig
from algofactory.web.data_view import samples, validation_errors
from algofactory.web.models import model_location, predict_text, prepare_model
from algofactory.web.service import Jobs, read_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--output-dir", type=Path, required=True)
    args = options.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "status": "in_progress",
        "paid_api_calls": 0,
        "final_test_attempted": False,
        "checks": [],
        "source_sha256": {
            str(p.relative_to(ROOT)): sha256_file(p) for p in sorted((ROOT / "src").rglob("*.py"))
        },
        "command": [sys.executable, *sys.argv],
    }
    write_json(out / "verification.json", summary)
    try:
        assert len(samples(ROOT)) == 7993
        errors, accuracy = validation_errors(
            ROOT, "examples/api-phase3/comparison", "candidates/text_logistic/attempt-1"
        )
        assert len(errors) == 253
        summary["data"] = {
            "train": 7993,
            "validation": 1999,
            "archived_errors": len(errors),
            "archived_accuracy": accuracy,
        }
        reports = []
        for name, config in [
            ("baseline", ExperimentConfig()),
            (
                "alternative",
                ExperimentConfig(ngram_max=1, max_features=10000, logistic_c=1.0, nb_alpha=0.5),
            ),
            ("single_nb", ExperimentConfig(algorithms=["text_nb"])),
        ]:
            configuration = out / (name + ".json")
            write_json(configuration, config.model_dump(mode="json"))
            result = run(
                parser().parse_args(
                    [
                        "demo",
                        "--task",
                        "banking77",
                        "--experiment",
                        str(configuration),
                        "--output-dir",
                        str(out / name),
                        "--db",
                        str(out / (name + ".sqlite")),
                        "--validation-only",
                        "--max-repairs",
                        "1",
                        "--llm-call-budget",
                        "12",
                    ]
                )
            )
            assert result["status"] == "validated", result
            report = read_json(out / name / "report.json")
            assert report["persisted"] and not report["test_attempted"]
            assert report["experiment_hash"] == config.digest
            reports.append(report)
        assert reports[0]["code_hash"] != reports[1]["code_hash"]
        assert reports[2]["candidate_mode"] == "single"
        summary["experiments"] = [
            {
                "workflow_id": r["workflow_id"],
                "code_hash": r["code_hash"],
                "experiment_hash": r["experiment_hash"],
                "validation_metrics": r["validation"]["validation_metrics"],
            }
            for r in reports
        ]
        # Submit the actual Streamlit form; its durable runner invokes the same CLI/core.
        from streamlit.testing.v1 import AppTest

        os.environ["ALGOFACTORY_PROJECT_ROOT"] = str(ROOT)
        app = AppTest.from_file(ROOT / "src/algofactory/web/app.py", default_timeout=90).run()
        assert not app.exception
        next(t for t in app.toggle if t.label == "自主选择算法与参数").set_value(True).run()
        next(s for s in app.multiselect if s.label == "参与实验的算法").set_value(
            ["text_logistic"]
        ).run()
        next(s for s in app.selectbox if s.label == "逻辑回归 C").set_value(1.0).run()
        next(b for b in app.button if b.label == "开始生成并验证").click().run()
        assert not app.exception
        identifier = app.session_state["current_job"]
        jobs = Jobs(ROOT)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = jobs.state(identifier)
            if state["status"] not in {"running", "queued"}:
                break
            time.sleep(0.25)
        assert state["status"] == "validated", state
        relative = f"runtime/web-jobs/{identifier}/run"
        app.run()
        assert not app.exception
        version = "candidates/text_logistic/attempt-0"
        errors, accuracy = validation_errors(ROOT, relative, version)
        report = read_json(ROOT / relative / "report.json")
        assert accuracy == report["validation"]["validation_metrics"]["accuracy"]
        assert next(s for s in app.selectbox if s.label == "选择开发任务").value == relative
        next(t for t in app.text_area if t.label == "新的英文咨询").set_value(
            "Yesterday a cash machine kept my bank card inside the machine and never gave it back."
        )
        next(b for b in app.button if b.label == "预测这条咨询").click().run()
        assert not app.exception and any("概率" in d.value.columns for d in app.dataframe)
        first = predict_text(
            ROOT,
            relative,
            version,
            "Yesterday a cash machine kept my bank card inside the machine and never gave it back.",
        )
        repeated = predict_text(
            ROOT,
            relative,
            version,
            "Yesterday a cash machine kept my bank card inside the machine and never gave it back.",
        )
        assert first == repeated
        summary["web"] = {
            "job_id": identifier,
            "status": state["status"],
            "report": relative,
            "experiment_hash": report["experiment_hash"],
            "validation_errors": len(errors),
            "prediction": first,
            "submission": "actual AppTest form and durable job subprocess",
            "prediction_form": "actual AppTest form",
            "final_test_attempted": report["test_attempted"],
        }
        shutil.copytree(ROOT / relative, out / "web-run")
        # Prepare an old validated version explicitly; it is never presented as historical weights.
        old = "examples/api-phase3/comparison"
        fixed = "candidates/text_logistic/attempt-1"
        location, _ = model_location(ROOT, old, fixed)
        if not (location / "model-provenance.json").exists():
            prepare_model(ROOT, old, fixed)
        summary["historical_preparation"] = predict_text(
            ROOT,
            old,
            fixed,
            "Yesterday a cash machine kept my bank card inside the machine and never gave it back.",
        )
        summary["image"] = read_json(ROOT / "runtime/docker-image.json")
        summary["status"] = "passed"
    except BaseException as exc:
        summary.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        write_json(out / "verification.json", summary)
    print(json.dumps({"status": summary["status"], "report": str(out / "verification.json")}))


if __name__ == "__main__":
    main()
