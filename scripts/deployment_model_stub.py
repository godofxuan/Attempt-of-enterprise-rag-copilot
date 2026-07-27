from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


_MAX_BODY_BYTES = 65_536
_MODEL_DIGEST = "a" * 64


class DeploymentModelStubHandler(BaseHTTPRequestHandler):
    embedding_dimension = 8
    model_names = (
        "deployment-smoke-chat",
        "deployment-smoke-evidence",
        "deployment-smoke-embed",
    )

    def do_GET(self) -> None:
        if self.path != "/api/tags":
            self._write_json(404, {"error": "not found"})
            return
        self._write_json(
            200,
            {
                "models": [
                    {"name": name, "digest": _MODEL_DIGEST}
                    for name in self.model_names
                ]
            },
        )

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self._write_json(400, {"error": "invalid request"})
            return
        model = payload.get("model")
        if model not in self.model_names:
            self._write_json(404, {"error": "unknown model"})
            return
        if self.path == "/api/embed":
            self._write_json(
                200,
                {"embeddings": [[1.0] * self.embedding_dimension]},
            )
            return
        if self.path == "/api/chat":
            self._write_json(200, {"message": {"content": "OK"}})
            return
        self._write_json(404, {"error": "not found"})

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("missing content length")
        length = int(raw_length)
        if not 0 <= length <= _MAX_BODY_BYTES:
            raise ValueError("request body exceeds limit")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return payload

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def build_server(
    host: str,
    port: int,
    *,
    embedding_dimension: int,
) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("deployment model stub must bind numeric IPv4 loopback")
    if not 1 <= embedding_dimension <= 65_536:
        raise ValueError("embedding dimension is invalid")
    handler = type(
        "ConfiguredDeploymentModelStubHandler",
        (DeploymentModelStubHandler,),
        {"embedding_dimension": embedding_dimension},
    )
    return ThreadingHTTPServer((host, port), handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CI-only local model protocol stub."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--embedding-dimension", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        server = build_server(
            args.host,
            args.port,
            embedding_dimension=args.embedding_dimension,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


__all__ = [
    "DeploymentModelStubHandler",
    "build_parser",
    "build_server",
    "main",
]
