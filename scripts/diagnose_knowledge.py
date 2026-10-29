#!/usr/bin/env python3
"""Explicit one-call knowledge diagnosis, or zero-call replay of a saved extraction."""

import argparse
import json
from pathlib import Path

from algofactory.datasets import sha256_file, write_json
from algofactory.knowledge.extraction import extraction_request, validate_extraction
from algofactory.llm.providers import APIConfig, APIProvider, ProviderError
from algofactory.schemas.knowledge import DocumentExtraction, Extraction, SourceDocument


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--env-file", type=Path)
    mode.add_argument("--response-file", type=Path)
    parser.add_argument("--document", type=Path, default=Path("data/banking77.txt"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = SourceDocument.from_text(args.document.name, args.document.read_text())
    summary = {
        "status": "failed",
        "mode": "api" if args.env_file else "offline_replay",
        "source_sha256": source.sha256,
        "error_category": None,
        "diagnostics": [],
        "code_sha256": {str(p): sha256_file(p) for p in sorted(Path("src").rglob("*.py"))},
    }
    provider = None
    try:
        if args.env_file:
            config = APIConfig.from_env(args.env_file)
            provider = APIProvider(
                config.model_copy(
                    update={
                        "max_calls": 1,
                        "max_retries": 0,
                        "max_output_tokens": min(config.max_output_tokens, 8192),
                    }
                )
            )
            response = provider.complete(extraction_request(source), DocumentExtraction)
            # Diagnostic retention is explicit. Never save a credential even if a service echoes it.
            encoded = response.model_dump_json()
            if config.api_key.get_secret_value() in encoded:
                raise ProviderError("sensitive_response_not_saved")
        else:
            response = Extraction.model_validate_json(args.response_file.read_bytes())
        write_json(args.output_dir / "extraction.json", response.model_dump(mode="json"))
        write_json(args.output_dir / "source.json", source.model_dump(mode="json"))
        batch = validate_extraction(source, response)
        summary.update(
            status="passed", entities=len(batch.entities), relations=len(batch.relations)
        )
    except ProviderError as exc:
        summary.update(error_category=exc.category, diagnostics=exc.diagnostics)
    except (ValueError, OSError):
        summary.update(error_category="diagnostic_input_invalid")
    finally:
        if provider:
            summary["usage"] = provider.usage_summary()
            write_json(
                args.output_dir / "provider-audit.json",
                [a.model_dump(mode="json") for a in provider.audit],
            )
        write_json(args.output_dir / "diagnosis.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "code_sha256"}, ensure_ascii=False, indent=2
        )
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
