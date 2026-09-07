"""Keep expensive model warmup out of periodic readiness probes."""

import re

import requests

from app.runtime.resources import RuntimeResources
from app.security.model_endpoint import parse_pinned_model_endpoint


class ServingRuntimeResources(RuntimeResources):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._verified_model_digests = None

    def refresh_if_stale(self):
        with self._refresh_lock:
            due = (
                self.started
                and not self.closed
                and self._last_checked_at is not None
                and self._clock() - self._last_checked_at
                >= float(self.settings.readiness_ttl_seconds) / 2
            )
        # Wake the existing worker early; never extend a snapshot's validity.
        if due:
            self.refresh_in_background()
        return super().refresh_if_stale()

    def _probe_models(self, index_info):
        if self._verified_model_digests is None:
            super()._probe_models(index_info)
            self._verified_model_digests = self._model_digests()
        elif self._model_digests() != self._verified_model_digests:
            raise RuntimeError("model identities changed; restart and revalidate")

    def _model_digests(self):
        origin = parse_pinned_model_endpoint(self.settings.llm_base_url).origin
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                f"{origin}/api/tags",
                timeout=self.settings.readiness_probe_timeout_seconds,
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise RuntimeError("model identity endpoint unavailable")
            tags = response.json()["models"]

        def normalized(name):
            return name.removesuffix(":latest")

        required = {
            normalized(name)
            for name in (
                self.settings.chat_model,
                self.settings.evidence_model,
                self.settings.embedding_model,
            )
        }
        digests = {}
        for item in tags:
            name = normalized(item["name"])
            if name not in required:
                continue
            value = item.get("digest")
            if (
                name in digests
                or not isinstance(value, str)
                or not re.fullmatch(r"[0-9a-f]{64}", value)
            ):
                raise RuntimeError("required model identity invalid or ambiguous")
            digests[name] = value
        if set(digests) != required or any(not digest for digest in digests.values()):
            raise RuntimeError("required model identity missing")
        return digests
