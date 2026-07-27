from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.indexing.store import load_active_pointer, load_index_version
from scripts.deployment_model_stub import build_server
from scripts.generate_deployment_sbom import build_python_sbom
from scripts.init_deployment_smoke_fixture import create_smoke_fixture
from scripts.probe_deployment import probe_deployment


def _request_json(
    port: int,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = (
            {
                "Content-Length": str(len(body)),
                "Content-Type": "application/json",
            }
            if body is not None
            else {}
        )
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        decoded = json.loads(response.read().decode("utf-8"))
        return response.status, decoded
    finally:
        connection.close()


def test_model_stub_implements_only_required_local_protocol() -> None:
    server = build_server("127.0.0.1", 0, embedding_dimension=8)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        tags_status, tags = _request_json(port, "GET", "/api/tags")
        embed_status, embed = _request_json(
            port,
            "POST",
            "/api/embed",
            {"model": "deployment-smoke-embed", "input": "probe"},
        )
        chat_status, chat = _request_json(
            port,
            "POST",
            "/api/chat",
            {"model": "deployment-smoke-chat", "messages": []},
        )
        missing_status, _ = _request_json(port, "GET", "/unknown")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert tags_status == 200
    assert len(tags["models"]) == 3
    assert embed_status == 200
    assert len(embed["embeddings"][0]) == 8
    assert chat_status == 200
    assert chat["message"]["content"] == "OK"
    assert missing_status == 404


class _ReadyApiHandler(BaseHTTPRequestHandler):
    index_run_id = "deployment-smoke-index-v1"

    def do_GET(self) -> None:
        if self.path == "/health/live":
            self._reply(200, {"status": "alive"})
        elif self.path == "/health/ready":
            self._reply(
                200,
                {
                    "status": "ready",
                    "index": {"run_id": self.index_run_id},
                },
            )
        else:
            self._reply(404, {"error": "not found"})

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_probe_requires_liveness_readiness_and_expected_index() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReadyApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        result = probe_deployment(
            f"http://127.0.0.1:{port}",
            deadline_seconds=2,
            request_timeout_seconds=1,
            expected_index_run_id="deployment-smoke-index-v1",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == {
        "index_run_id": "deployment-smoke-index-v1",
        "liveness": "alive",
        "readiness": "ready",
    }


def test_probe_rejects_non_loopback_targets() -> None:
    with pytest.raises(ValueError, match="numeric IPv4 loopback"):
        probe_deployment(
            "http://example.com:8000",
            deadline_seconds=1,
            request_timeout_seconds=1,
        )


def test_smoke_fixture_has_good_and_intentionally_incompatible_indexes(
    tmp_path: Path,
) -> None:
    payload = create_smoke_fixture(tmp_path / "smoke")
    index_root = Path(str(payload["index_root"]))

    good = load_index_version(index_root, "deployment-smoke-index-v1")
    candidate = load_index_version(index_root, "deployment-smoke-index-v2")

    assert good.manifest.embedding.dimension == 8
    assert candidate.manifest.embedding.dimension == 7
    assert load_active_pointer(index_root).run_id == "deployment-smoke-index-v1"
    assert (Path(str(payload["identity_root"])) / "jwks.json").is_file()


def test_python_sbom_is_spdx_and_binds_image_and_source() -> None:
    image = "ghcr.io/example/rag@sha256:" + "a" * 64
    commit = "b" * 40

    sbom = build_python_sbom(
        image_reference=image,
        source_commit=commit,
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert sbom["x_image_reference"] == image
    assert sbom["x_source_commit"] == commit
    assert sbom["creationInfo"]["created"] == "2026-07-27T12:00:00Z"
    assert len(sbom["packages"]) > 10
    assert len(sbom["relationships"]) == len(sbom["packages"])
