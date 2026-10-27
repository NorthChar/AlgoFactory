"""Expose scaffold status without pretending to run an algorithm workflow."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description="AlgoFactory Phase 0 骨架")
    parser.add_argument("command", choices=["status"])
    parser.parse_args()
    print(json.dumps({"phase": 0, "status": "scaffold", "core_workflow": "not_implemented"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
