from __future__ import annotations

from typing import Sequence

from app.evaluation.indirect_injection_exposure_public_verifier import (
    main as verifier_main,
)


def main(argv: Sequence[str] | None = None) -> int:
    return verifier_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

