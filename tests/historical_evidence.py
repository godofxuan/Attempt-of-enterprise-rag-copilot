"""Read the immutable source revision named by a historical evidence release."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_20260915 = "caf90441cbdae5606436ae44f6c194f4f5fa22a8"


def release_bytes(relative):
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "show", RELEASE_20260915 + ":" + relative]
    )
