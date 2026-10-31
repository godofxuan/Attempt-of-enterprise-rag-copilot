"""Real parsers, FAISS, jobs, SQLite and source visibility; no real inference."""

import asyncio

from tests.product.test_turn_recovery import product


def test_pending_replacement_failure_withdrawal_restore_and_restart(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        kb = w.library.create("原子发布")["id"]

        async def embed(texts, **kwargs):
            return [[1.0, float(len(text) % 7 + 1)] for text in texts]

        async def identity():
            return "1" * 64

        w.models.embed, w.models.embedding_identity = embed, identity
        one = c.portal.call(w.library.upload, kb, "one.md", b"# One\n\nLoan lasts 14 days.\n")
        two = c.portal.call(w.library.upload, kb, "two.md", b"# Two\n\nMeeting lasts 4 hours.\n")

        async def build():
            job = w.library.enqueue(kb, changed=True)
            await asyncio.gather(*w.library.running)
            return job

        first = c.portal.call(build)
        old = w.library.snapshot(kb)
        assert w.library.published_scope(old) == {one["id"], two["id"]}
        replacement = c.portal.call(
            w.library.upload, kb, "one.md", b"# One\n\nLoan now lasts 7 days.\n"
        )
        assert w.library.snapshot(kb).version.manifest.run_id == first["id"]
        assert one["id"] in w.library.published_scope(old)  # update, not revocation

        async def fail(*args, **kwargs):
            raise ConnectionError("explicit build failure")

        w.models.embedding_identity = fail
        c.portal.call(build)
        state = w.library.publication_state(kb)
        assert state["update_state"] == "FAILED" and state["published_run_id"] == first["id"]
        assert w.library.snapshot(kb).version.manifest.run_id == first["id"]
        # Withdrawing the source revokes all published versions of its source key.
        w.library.update_document(replacement["id"], {"active": False})
        assert w.library.published_scope(old) == {two["id"]}
        w.library.update_document(replacement["id"], {"active": True})
        assert w.library.published_scope(old) == {one["id"], two["id"]}
        w.models.embedding_identity = identity
        final = c.portal.call(build)
        current = w.library.snapshot(kb)
        assert current.version.manifest.run_id == final["id"]
        assert w.library.published_scope(current) == {replacement["id"], two["id"]}
        assert w.library.excerpt(one["id"], first["id"], "document", one["id"])["text"]
    with product(tmp_path) as c:
        w = c.app.state.workspace
        assert w.library.snapshot(kb).version.manifest.run_id == final["id"]
        assert w.library.published_scope(w.library.snapshot(kb)) == {replacement["id"], two["id"]}


def test_actual_hash_router_entry_without_masking_api_errors(tmp_path):
    with product(tmp_path) as c:
        response = c.get("/")
        assert response.status_code == 200 and "/ui/assets/" in response.text
        assert c.get("/api/not-a-route").status_code == 404
