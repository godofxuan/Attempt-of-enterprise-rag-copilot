"""Calendar/date semantics and a derived preview state; not production authorization."""
from dataclasses import dataclass
from datetime import date, timedelta

def interval(start: str, inclusive_end: str) -> tuple[date, date]:
    a, b = date.fromisoformat(start), date.fromisoformat(inclusive_end)
    if b < a:
        raise ValueError("end precedes start")
    return a, b + timedelta(days=1)

def overlaps(a: tuple[date, date], b: tuple[date, date]) -> bool:
    return a[0] < b[1] and a[1] > b[0]

@dataclass(frozen=True)
class Preview:
    expires_at: float
    revision: int

def preview_state(preview: Preview, *, now: float, current_revision: int) -> str:
    if preview.revision != current_revision:
        return "stale"
    if now >= preview.expires_at:
        return "expired"
    return "current"

if __name__ == "__main__":
    old = interval("2026-11-01", "2026-11-03")
    print("Nov 3 overlap", overlaps(old, interval("2026-11-03", "2026-11-04")))
    print("Nov 4 overlap", overlaps(old, interval("2026-11-04", "2026-11-05")))
    print("deadline state", preview_state(Preview(600, 2), now=600, current_revision=2))
