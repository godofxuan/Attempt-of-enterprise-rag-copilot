"""Index default admission uses the same UTC day as current-version retrieval."""

from datetime import date, datetime, timezone
import asyncio
import json
from types import SimpleNamespace

from tests.product.test_turn_recovery import product


def test_implicit_admission_day_matches_utc_and_preserves_declared_dates(tmp_path, monkeypatch):
    import app.knowledge.jobs as jobs

    class LocalTomorrow:
        @staticmethod
        def today():
            return date(2026, 10, 31)

    class UTCClock:
        @staticmethod
        def now(tz):
            assert tz == timezone.utc
            return datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(jobs, "date", LocalTomorrow, raising=False)
    monkeypatch.setattr(jobs, "datetime", UTCClock, raising=False)
    with product(tmp_path) as client:
        library = client.app.state.workspace.library
        kb = library.create("UTC技术准入测试")["id"]

        async def documents():
            first = await library.upload(
                kb, "implicit.md", "普通资料未声明生效日期。".encode("utf8")
            )
            second = await library.upload(
                kb, "declared.md", "另一份资料明确约定未来生效。".encode("utf8")
            )
            return first, second

        first, second = asyncio.run(documents())
        library.update_document(second["id"], {"effective_from": "2026-11-05"})
        captured = []

        def build(**kwargs):
            captured.append(json.loads((kwargs["input_dir"] / "manifest.json").read_text("utf8")))
            return SimpleNamespace(run_id="clock-probe", indexed_chunk_count=2)

        # Only intercept the final index writer to inspect the real assembled manifest.
        monkeypatch.setattr("app.indexing.store.build_index_version", build)
        library._build("clock-probe", kb, lambda text: [1.0, 0.0], "1" * 64)
        meta = {d["doc_id"]: d["metadata"] for d in captured[0]["documents"]}
        assert meta[first["id"]]["effective_from"] == "2026-10-30"
        assert meta[second["id"]]["effective_from"] == "2026-11-05"
