"""Request-local references to admitted snapshot resources, never model authority."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from app.domain.agent import AgentAction
from app.domain.queries import FindRequest, OpenRequest
from app.domain.retrieved_security import GuardedFindResult, GuardedOpenAdmittedResult, GuardedSearchResult


class InvalidReference(ValueError):
    pass


@dataclass(frozen=True)
class DocumentCapability:
    anchor: object
    scope_hash: str
    observation_id: str


@dataclass(frozen=True)
class WindowCapability:
    document_ref: str
    target_id: str
    start: int
    length: int
    content_hash: str
    observation_id: str
    preview: str


class RequestCapabilities:
    def __init__(self, registry, state, index_binding=None):
        self.nonce = secrets.token_hex(16)
        self.registry = registry
        self.snapshot = registry.navigation_snapshot
        self.scope_hash = self._scope(state)
        self.documents: dict[str, DocumentCapability] = {}
        self.admitted_chunks: dict[str, object] = {}
        self.windows: dict[str, WindowCapability] = {}
        self.used_windows: set[str] = set()
        self.sealed = False
        self.index_binding = index_binding
        self.pointer = None
        if index_binding is not None:
            from app.indexing.store import load_active_pointer
            self.pointer = load_active_pointer(index_binding[0])

    @staticmethod
    def _scope(state):
        return hashlib.sha256((state.user.model_dump_json() + state.analysis.filters.model_dump_json()).encode()).hexdigest()

    def check(self, state):
        if self.sealed or self.scope_hash != self._scope(state):
            raise InvalidReference("reference unavailable")
        if self.snapshot is None or self.registry.navigator.snapshot is not self.snapshot:
            raise InvalidReference("snapshot unavailable")
        if self.index_binding is not None:
            from app.indexing.store import load_active_pointer
            pointer = load_active_pointer(self.index_binding[0])
            if pointer != self.pointer or (pointer.run_id, pointer.manifest_sha256) != self.index_binding[1:]:
                raise InvalidReference("snapshot unavailable")

    def _ref(self, kind, count):
        return f"{kind}{count}_{self.nonce[:16]}"

    def admit_search(self, result, state, observation_id):
        self.check(state)
        if not isinstance(result, GuardedSearchResult):
            raise TypeError("capabilities require admitted search")
        if (result.index_run_id, result.manifest_sha256) != (self.snapshot.version.manifest.run_id, self.snapshot.version.manifest_sha256):
            raise InvalidReference("search snapshot unavailable")
        for item in result.hits:
            self.admitted_chunks[item.hit.chunk_id]=item
            if any(c.anchor.hit.doc_id == item.hit.doc_id for c in self.documents.values()):
                continue
            ref = self._ref("D", len(self.documents) + 1)
            self.documents[ref] = DocumentCapability(item, self.scope_hash, observation_id)

    def document_view(self):
        from app.domain.evidence_packet import complete_evidence_prefix
        result=[]
        for ref,cap in list(self.documents.items())[:8]:
            text="\n".join(dict.fromkeys(c.hit.matched_text for c in self.admitted_chunks.values()
                                      if c.hit.doc_id==cap.anchor.hit.doc_id)) or cap.anchor.hit.matched_text
            excerpt=complete_evidence_prefix(text,700)
            result.append({"kind":"document","ref":ref,"title":"/".join(cap.anchor.hit.section_path)[:180],
                "excerpt":excerpt,"is_complete_source_unit":excerpt==text,
                "context_status":"FULL" if excerpt==text else "PARTIAL_COMPLETE_UNITS" if excerpt else "CONTEXT_INSUFFICIENT"})
        return result

    def resolve_find(self, action, state):
        self.check(state)
        cap = self.documents.get(action.document_ref)
        if cap is None or action.section_ref is not None:
            raise InvalidReference("reference unavailable")
        return AgentAction(sequence=state.budget_state.steps+1, tool="find", purpose="locate requested source text",
            find_request=FindRequest(request_id=self.nonce, user=state.user, doc_id=cap.anchor.hit.doc_id,
                anchor_chunk_id=cap.anchor.hit.chunk_id, filters=state.analysis.filters,
                pattern=action.pattern, max_results=4))

    def admit_find(self, action, result, state, observation_id):
        self.check(state)
        if not isinstance(result, GuardedFindResult):
            raise TypeError("capabilities require admitted find")
        doc_ref = next((ref for ref, cap in self.documents.items() if cap.anchor.hit.doc_id == action.find_request.doc_id), None)
        if doc_ref is None:
            raise InvalidReference("reference unavailable")
        refs = []
        for item in result.matches:
            match = item.match
            resource = self.snapshot.all_chunks_by_id.get(match.chunk_id)
            if resource is None or not self.registry.navigator.bound_resource_allowed(action.find_request, resource):
                raise InvalidReference("window unavailable")
            # A find preview is location evidence, not a delivered quotation.
            start = 0 if resource.kind == "table" else match.preview_start
            length = min(1600, len(resource.text) - start)
            text = resource.text[start:start+length]
            key = (doc_ref, resource.chunk_id, start, length, hashlib.sha256(text.encode()).hexdigest())
            ref = next((r for r, w in self.windows.items() if (w.document_ref,w.target_id,w.start,w.length,w.content_hash) == key), None)
            if ref is None:
                ref = self._ref("W", len(self.windows)+1)
                self.windows[ref] = WindowCapability(*key, observation_id, match.preview)
            refs.append({"kind": "window", "ref": ref, "excerpt": match.preview, "is_complete_source_unit": False})
        return refs

    def resolve_open(self, action, state):
        self.check(state)
        cap = self.windows.get(action.window_ref)
        if cap is None or action.window_ref in self.used_windows:
            raise InvalidReference("reference unavailable")
        doc = self.documents[cap.document_ref]
        resource = self.snapshot.all_chunks_by_id.get(cap.target_id)
        if resource is None or hashlib.sha256(resource.text[cap.start:cap.start+cap.length].encode()).hexdigest() != cap.content_hash:
            raise InvalidReference("window unavailable")
        return AgentAction(sequence=state.budget_state.steps+1, tool="open", purpose="read admitted source window",
            open_request=OpenRequest(request_id=self.nonce, user=state.user, target_type="chunk",
                target_id=cap.target_id, anchor_chunk_id=doc.anchor.hit.chunk_id, filters=state.analysis.filters,
                start_char=cap.start, max_chars=cap.length))

    def continuation(self, ref, opened, state, observation_id):
        self.check(state)
        cap = self.windows[ref]
        resource = self.snapshot.all_chunks_by_id[cap.target_id]
        end = cap.start + len(opened.result.content)
        if end >= len(resource.text):
            return None
        from app.domain.evidence_packet import SOURCE_UNIT_END
        boundaries = [m.end() for m in SOURCE_UNIT_END.finditer(resource.text[:end])]
        start = boundaries[-1] if boundaries else cap.start
        if start <= cap.start or resource.kind == "table":
            return None
        length = min(1600, len(resource.text)-start)
        key = (cap.document_ref, cap.target_id, start, length,
               hashlib.sha256(resource.text[start:start+length].encode()).hexdigest())
        new_ref = self._ref("W", len(self.windows)+1)
        self.windows[new_ref] = WindowCapability(*key, observation_id, "")
        return {"kind": "window", "ref": new_ref, "excerpt": "", "is_complete_source_unit": False}

    def seal(self):
        self.sealed = True
        self.documents.clear()
        self.admitted_chunks.clear()
        self.windows.clear()
