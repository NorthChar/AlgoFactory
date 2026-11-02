"""Execute two locally parsed requirements through real Docker, using Mock only."""

import argparse
import shutil
from pathlib import Path

from algofactory.cli import parser, run
from algofactory.datasets import sha256_file, write_json
from algofactory.requirements import EXAMPLE_REQUEST, interpret_requirement
from algofactory.web.service import read_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--output-dir", type=Path, required=True)
    out = options.parse_args().output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "status": "running",
        "paid_api_calls": 0,
        "final_test_attempted": False,
        "cases": [],
        "source_sha256": {
            str(p.relative_to(ROOT)): sha256_file(p) for p in sorted((ROOT / "src").rglob("*.py"))
        },
    }
    write_json(out / "verification.json", summary)
    try:
        for name, request, fault in [
            ("logistic", EXAMPLE_REQUEST, "repairable_interface"),
            (
                "nb",
                "开发英文银行咨询分类算法；只使用朴素贝叶斯；使用单词和相邻双词特征；词表上限30000；朴素贝叶斯平滑系数=0.1",
                None,
            ),
        ]:
            config = interpret_requirement(request).experiment
            assert config is not None
            directory = out / name
            directory.mkdir()
            shutil.copytree(ROOT / "runtime/banking77-data", directory / "dataset")
            write_json(directory / "experiment.json", config.model_dump(mode="json"))
            (directory / "request.txt").write_text(request, encoding="utf-8")
            arguments = [
                "demo",
                "--task",
                "banking77",
                "--mode",
                "mock",
                "--request",
                request,
                "--experiment",
                str(directory / "experiment.json"),
                "--dataset-dir",
                str(directory / "dataset"),
                "--output-dir",
                str(directory / "run"),
                "--db",
                str(directory / "knowledge.sqlite"),
                "--validation-only",
                "--max-repairs",
                "2",
                "--llm-call-budget",
                "24",
            ]
            if fault:
                arguments += ["--fault", fault]
            result = run(parser().parse_args(arguments))
            report = read_json(directory / "run/report.json")
            attempts = read_json(directory / "run/attempts.json")
            assert report["persisted"] and not report["test_attempted"]
            assert report["experiment_hash"] == config.digest
            for attempt in attempts:
                child = (
                    directory
                    / "run/candidates"
                    / attempt["algorithm"]
                    / f"attempt-{attempt['attempt']}"
                )
                assert read_json(child / "task.json")["description"] == request
                assert read_json(child / "report.json")["experiment_hash"] == config.digest
            assert result["status"] == "validated", result
            if fault:
                assert any(a["attempt"] > 0 and a["status"] == "validated" for a in attempts)
            summary["cases"].append(
                {
                    "name": name,
                    "request": request,
                    "configuration": config.frozen(),
                    "configuration_hash": config.digest,
                    "attempts": len(attempts),
                    "status": result["status"],
                    "validation_metrics": result["validation_metrics"],
                    "persisted": report["persisted"],
                    "injected_mock_fault": fault,
                }
            )
        summary["status"] = "passed"
    except Exception:
        summary["status"] = "failed"
        raise
    finally:
        write_json(out / "verification.json", summary)
    print("Requirement execution checks passed; no paid API calls or final tests.")


if __name__ == "__main__":
    main()
