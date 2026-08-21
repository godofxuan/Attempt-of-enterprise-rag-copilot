from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent_runtime.harness_contract import HarnessOutputV1, HarnessRequestV1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate enterprise Agent harness v1 JSON schemas."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/production_runtime/schemas"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "agent_harness_request_v1.schema.json": HarnessRequestV1.model_json_schema(),
        "agent_harness_result_v1.schema.json": HarnessOutputV1.model_json_schema(),
    }
    for name, schema in outputs.items():
        (args.output_dir / name).write_text(
            json.dumps(schema, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"generated": sorted(outputs)}, indent=2))


if __name__ == "__main__":
    main()
