from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from app.deployment.releases import COMMIT_PATTERN, IMAGE_REFERENCE_PATTERN


def _spdx_id(name: str, ordinal: int) -> str:
    safe = re.sub(r"[^A-Za-z0-9.-]", "-", name)
    return f"SPDXRef-Package-{safe}-{ordinal}"


def build_python_sbom(
    *,
    image_reference: str,
    source_commit: str,
    created_at: datetime | None = None,
) -> dict[str, object]:
    if not IMAGE_REFERENCE_PATTERN.fullmatch(image_reference):
        raise ValueError("SBOM image reference must contain an exact sha256 digest")
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("SBOM source commit must be an exact Git commit")
    created = created_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("SBOM creation time must be timezone-aware")

    distributions = sorted(
        (
            (distribution.metadata.get("Name") or distribution.name, distribution.version)
            for distribution in importlib.metadata.distributions()
        ),
        key=lambda item: (item[0].lower(), item[1]),
    )
    packages = []
    relationships = []
    for ordinal, (name, version) in enumerate(distributions, start=1):
        spdx_id = _spdx_id(name, ordinal)
        packages.append(
            {
                "SPDXID": spdx_id,
                "downloadLocation": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceLocator": (
                            f"pkg:pypi/{quote(name.lower())}@{quote(version)}"
                        ),
                        "referenceType": "purl",
                    }
                ],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "name": name,
                "supplier": "NOASSERTION",
                "versionInfo": version,
            }
        )
        relationships.append(
            {
                "relatedSpdxElement": spdx_id,
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            }
        )

    namespace_digest = hashlib.sha256(
        f"{image_reference}\0{source_commit}".encode("ascii")
    ).hexdigest()
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": created.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "creators": ["Tool: enterprise-rag-python-sbom-v1"],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": (
            "https://enterprise-rag.local/sbom/" + namespace_digest
        ),
        "name": "enterprise-rag-python-runtime",
        "packages": packages,
        "relationships": relationships,
        "spdxVersion": "SPDX-2.3",
        "x_image_reference": image_reference,
        "x_source_commit": source_commit,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a Python-package SPDX SBOM for the runtime image."
    )
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = build_python_sbom(
            image_reference=args.image_reference,
            source_commit=args.source_commit,
        )
        target = args.output.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
            + "\n",
            encoding="ascii",
            newline="\n",
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "output": str(target),
                "package_count": len(payload["packages"]),
                "status": "generated",
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "build_python_sbom", "main"]
