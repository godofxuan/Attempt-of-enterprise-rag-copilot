from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

import requests

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.external_datasets.uda_finance import UDA_HF_REVISION


ARCHIVE_URL = (
    "https://huggingface.co/datasets/qinchuanhui/UDA-QA/resolve/"
    f"{UDA_HF_REVISION}/src_doc_files/fin_docs.zip?download=true"
)
ARCHIVE_SIZE = 2_405_128_290
ARCHIVE_SHA256 = "e94f2eb0b80817521e3ab55cc494789b531697f77679cc75b6f953f64669dd44"
ARCHIVE_XET_ETAG = "354563684de84b55c1328265fe7dd6f6780bc198cca5e9d00b889e099c7842a3"
DEFAULT_OUTPUT = (
    Path(".private")
    / "external"
    / "uda_finance"
    / "upstream"
    / "fin_docs.zip"
)
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resume and verify the pinned UDA FinHybrid PDF archive."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-attempts", type=int, default=40)
    parser.add_argument("--read-timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    if args.max_attempts < 1 or args.max_attempts > 100:
        raise ValueError("max attempts must be between 1 and 100")
    if args.read_timeout_seconds < 10 or args.read_timeout_seconds > 600:
        raise ValueError("read timeout must be between 10 and 600 seconds")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    if output.exists() and output.stat().st_size < ARCHIVE_SIZE:
        if partial.exists():
            raise FileExistsError("both partial UDA archive paths exist")
        output.replace(partial)
    if output.exists():
        _verify_complete(output)
        print(str(output))
        return 0
    if partial.exists() and partial.stat().st_size > ARCHIVE_SIZE:
        raise ValueError("partial UDA archive exceeds the pinned size")

    session = requests.Session()
    attempt = 0
    while _size(partial) < ARCHIVE_SIZE and attempt < args.max_attempts:
        attempt += 1
        start = _size(partial)
        headers = {
            "Range": f"bytes={start}-",
            "If-Range": f'"{ARCHIVE_XET_ETAG}"',
        }
        try:
            with session.get(
                ARCHIVE_URL,
                headers=headers,
                allow_redirects=True,
                stream=True,
                timeout=(30, args.read_timeout_seconds),
            ) as response:
                _validate_partial_response(response, expected_start=start)
                next_report = start + 128 * 1024 * 1024
                with partial.open("ab") as sink:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        sink.write(chunk)
                        current = sink.tell()
                        if current >= next_report or current == ARCHIVE_SIZE:
                            print(
                                f"UDA archive {current}/{ARCHIVE_SIZE} bytes",
                                file=sys.stderr,
                                flush=True,
                            )
                            next_report = current + 128 * 1024 * 1024
                    sink.flush()
                    os.fsync(sink.fileno())
        except (requests.RequestException, OSError) as exc:
            print(
                f"UDA archive attempt {attempt} paused at {_size(partial)} bytes: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if attempt < args.max_attempts:
                time.sleep(min(30, attempt * 2))
    if _size(partial) != ARCHIVE_SIZE:
        raise RuntimeError(
            f"UDA archive incomplete after {attempt} attempts: "
            f"{_size(partial)}/{ARCHIVE_SIZE} bytes"
        )
    _verify_complete(partial)
    partial.replace(output)
    print(str(output))
    return 0


def _validate_partial_response(response: requests.Response, *, expected_start: int) -> None:
    if response.status_code != 206:
        raise RuntimeError(
            f"UDA archive resume requires HTTP 206, got {response.status_code}"
        )
    content_range = response.headers.get("content-range", "")
    match = _CONTENT_RANGE.fullmatch(content_range)
    if match is None:
        raise RuntimeError("UDA archive response has no valid Content-Range")
    start, end, total = (int(value) for value in match.groups())
    if start != expected_start or end < start or total != ARCHIVE_SIZE:
        raise RuntimeError(
            f"UDA archive range mismatch: {content_range!r}"
        )
    etag = response.headers.get("etag", "").strip('"')
    if etag != ARCHIVE_XET_ETAG:
        raise RuntimeError(f"UDA archive ETag mismatch: {etag!r}")


def _verify_complete(path: Path) -> None:
    if path.stat().st_size != ARCHIVE_SIZE:
        raise ValueError("UDA archive byte count mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("UDA archive SHA-256 mismatch")


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


if __name__ == "__main__":
    raise SystemExit(main())
