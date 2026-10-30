"""Audit tracked files and optional reachable Git history without emitting secret values."""

import argparse
import json
from pathlib import Path

from algofactory.datasets import write_json
from algofactory.delivery import audit_release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history", action="store_true")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Use the current configured key only as an exact secret scanner input",
    )
    args = parser.parse_args()
    secrets = ()
    if args.env_file:
        from algofactory.llm.providers import APIConfig

        secrets = (APIConfig.from_env(args.env_file).api_key.get_secret_value().encode(),)
    result = audit_release(
        Path(__file__).resolve().parents[1], secrets=secrets, history=args.history
    )
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "files": result["tracked_files"],
                "findings": result["findings"],
            }
        )
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
