try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
from pathlib import Path

from app.external_datasets.finqa_typed_retrospective import (
    build_public_evidence,
    canonical_json_bytes,
    load_protocol,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate-only FinQA typed retrospective evidence."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = load_protocol(args.protocol)
    evidence = build_public_evidence(
        run_dir=args.run_dir,
        protocol=protocol,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"public evidence already exists: {output}")
    output.write_bytes(
        canonical_json_bytes(
            evidence.model_dump(mode="json"),
            newline=True,
        )
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
