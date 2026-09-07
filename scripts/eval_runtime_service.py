"""Frozen real-model, authenticated in-process API acceptance and resource run."""

import argparse
import hashlib
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def source_identity():
    files = {path.as_posix(): sha(path) for path in sorted(Path("app").rglob("*.py"))}
    return dict(
        git_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
        app_sources_sha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        app_sources=files,
        harness_sha256=sha(__file__),
    )


def normalized(text):
    return "".join(text.casefold().split())


def score_response(case, status, response, snapshot):
    """Finite phrase/source contracts only. No inference of semantic human truth."""
    text = normalized(response.get("answer", ""))
    sources = response.get("sources", [])
    source_ids = {row.get("doc_id") for row in sources}
    expected = case["expected_facts"]
    matched = sum(normalized(fact) in text for fact in expected)
    forbidden = [
        item
        for item in case["forbidden_strings"]
        if normalized(item) in normalized(json.dumps(response, ensure_ascii=False))
    ]
    references, invalid = 0, 0
    from app.domain.queries import UserContext
    from app.security.access import AccessPolicy
    from app.security.demo_identity import _PERSONAS

    groups = next(persona["groups"] for persona in _PERSONAS if persona["sub"] == case["persona"])
    user = UserContext(
        user_id=case["persona"], tenant_id="starbridge-cn", region="cn", groups=groups
    )
    unauthorized = sum(
        source.get("doc_id") not in snapshot.documents_by_id
        or not AccessPolicy().evaluate(user, snapshot.documents_by_id[source["doc_id"]]).allowed
        for source in sources
    )
    source_map = {row.get("chunk_id"): row for row in sources}
    for citation in response.get("citations", []):
        for citation_id in citation.get("cited_chunk_ids", []):
            references += 1
            source = source_map.get(citation_id)
            doc = snapshot.documents_by_id.get(source.get("doc_id")) if source else None
            if doc is None:
                invalid += 1
                continue
            spans = citation.get("supporting_spans", [])
            if any(
                span["index_run_id"] != snapshot.version.manifest.run_id
                or span["version_id"] != doc.document_version.version_id
                or span["quote"] not in doc.text
                for span in spans
            ):
                invalid += 1
    mode_ok = status == 200 and response.get("mode") in case["expected_modes"]
    source_complete = set(case["gold_doc_ids"]).issubset(source_ids)
    correct = (
        mode_ok
        and matched == len(expected)
        and source_complete
        and not forbidden
        and invalid == 0
        and unauthorized == 0
    )
    unsafe_steps = (
        sum(
            response.get("trace", {}).get("budget", {}).get(k, 0)
            for k in ("search_calls", "find_calls", "open_calls")
        )
        if case["expected_modes"] == ["unsafe"]
        else 0
    )
    if unsafe_steps:
        correct = False
    return dict(
        contract_complete=correct,
        mode_ok=mode_ok,
        fact_count=len(expected),
        matched_facts=matched,
        source_complete=source_complete,
        citation_references=references,
        invalid_references=invalid,
        forbidden_publication_count=len(forbidden),
        unsafe_tool_calls=unsafe_steps,
        unauthorized_sources=unauthorized,
        known_security_failure=bool(forbidden or invalid or unsafe_steps or unauthorized),
        answer_semantics="NOT_HUMAN_REVIEWED",
    )


class ResourceSampler:
    def __init__(self):
        self.stop = threading.Event()
        self.samples = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import ctypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                )
            ]

        while not self.stop.is_set():
            row = {"monotonic": time.monotonic()}
            if os.name == "nt":
                counters = MemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
                if ctypes.windll.psapi.GetProcessMemoryInfo(
                    ctypes.c_void_p(ctypes.windll.kernel32.GetCurrentProcess()),
                    ctypes.byref(counters),
                    counters.cb,
                ):
                    row["process_rss_bytes"] = counters.WorkingSetSize
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                memory, utilization = result.stdout.strip().splitlines()[0].split(",")
                row.update(
                    gpu_total_used_mib=int(memory.strip()),
                    gpu_utilization_percent=int(utilization.strip()),
                )
            except Exception:
                row["gpu_sampling"] = "unavailable"
            self.samples.append(row)
            self.stop.wait(1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, help="Explicit separately frozen repair protocol")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be fresh; failed requests are not resumed or replaced")
    protocol_path = args.protocol or args.assets / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf8"))
    if protocol["status"] != "FROZEN_BEFORE_SERVICE_RUN" or len(protocol["cases"]) != 40:
        raise ValueError("invalid protocol")
    args.output.mkdir(parents=True)
    indexes = (args.assets / "indexes").resolve()
    for version, expected in protocol["index_manifests"].items():
        if sha(indexes / "versions" / version / "manifest.json") != expected:
            raise ValueError("index identity mismatch")
    os.environ["V2_INDEXES_DIR"] = str(indexes)
    os.environ["V2_RERANKER_DEVICE"] = "cuda"
    # Explicitly isolate runtime state, without replacing production indexes or identity.
    os.environ["SQLITE_PATH"] = str((args.output / "service.db").resolve())
    from app.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.indexing.store import activate_version, load_active_pointer
    from app.retrieval.snapshot import V2IndexSnapshot
    from app.runtime.resources import build_service_container
    from app.security.demo_identity import initialize_demo_identity
    from app.serving import create_app

    initial = source_identity()
    settings = get_settings()
    if settings.v2_indexes_dir.resolve() != indexes:
        raise ValueError("service settings failed to bind isolated index")
    if settings.sqlite_path.resolve() != (args.output / "service.db").resolve():
        raise ValueError("service database is not isolated")
    import platform

    import torch

    from app.retrieval.reranker_identity import MODEL_ID, REVISION, verify_reranker_identity
    from app.retrieval.serving_config import ServingRetrievalSettings

    reranker_files = verify_reranker_identity(ServingRetrievalSettings().reranker_path.resolve())
    import requests

    with requests.Session() as session:
        session.trust_env = False
        models = session.get("http://127.0.0.1:11434/api/tags", timeout=5).json()["models"]
    identities = {model["name"]: model["digest"] for model in models}
    manifest = dict(
        source=initial,
        hardware={
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        reranker={"model": MODEL_ID, "revision": REVISION, "verified_files": reranker_files},
        protocol_sha256=sha(protocol_path),
        model_identities=identities,
        settings={
            key: getattr(settings, key)
            for key in (
                "chat_model",
                "evidence_model",
                "embedding_model",
                "agent_v2_deadline_ms",
                "model_request_timeout_seconds",
                "structured_generation_max_attempts",
            )
        },
        argv=["--assets", "<D-private-assets>", "--output", "<D-private-results>"],
        client="real FastAPI in-process ASGI; no network SLA",
        started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
    snapshots = {
        version: V2IndexSnapshot.load(indexes, version) for version in protocol["index_manifests"]
    }
    rows, warmups, resources, startup = [], [], [], []
    with (
        (args.output / "rows.jsonl").open("x", encoding="utf8") as out,
        ResourceSampler() as sampler,
    ):

        def append(row):
            out.write(json.dumps(row, ensure_ascii=True) + "\n")
            out.flush()

        for repeat in range(protocol["repeats"]):
            arms = protocol["profiles"][repeat:] + protocol["profiles"][:repeat]
            for arm in arms:
                if source_identity()["app_sources_sha256"] != initial["app_sources_sha256"]:
                    raise RuntimeError("source changed during measurement")
                os.environ["V2_RETRIEVAL_PROFILE"] = arm
                block = f"r{repeat}-{arm}"
                identity = (args.output / "identities" / block).resolve()
                initialize_demo_identity(
                    identity,
                    issuer=settings.identity_issuer,
                    audience=settings.identity_audience,
                    token_lifetime_seconds=900,
                )
                tokens = json.loads((identity / "persona_tokens.json").read_bytes())["tokens"]
                block_settings = settings.model_copy(
                    update={
                        "identity_jwks_path": identity / "jwks.json",
                        "identity_feedback_hmac_key_path": identity / "feedback_actor_hmac.key",
                    }
                )
                service = build_service_container(block_settings)
                activate_version(indexes, "base")
                begin = time.perf_counter()
                with TestClient(create_app(service)) as client:
                    ready = client.get("/health/ready")
                    while ready.status_code != 200 and time.perf_counter() - begin < 120:
                        time.sleep(1)
                        ready = client.get("/health/ready")
                    startup.append(
                        dict(
                            block=block,
                            seconds=time.perf_counter() - begin,
                            ready=ready.status_code,
                        )
                    )
                    print(json.dumps(startup[-1]), flush=True)
                    if ready.status_code != 200:
                        (args.output / "readiness_failure.json").write_text(
                            json.dumps(ready.json()), encoding="utf8"
                        )
                        raise RuntimeError(
                            "service did not become ready; no fake resource fallback"
                        )

                    def request(
                        case,
                        kind,
                        ordinal,
                        *,
                        repeat=repeat,
                        arm=arm,
                        tokens=tokens,
                        service=service,
                        client=client,
                    ):
                        request_id = (
                            f"rc6-{repeat}-{protocol['profiles'].index(arm)}-{kind}-{ordinal}"
                        )
                        started = time.perf_counter()
                        request_started_monotonic = time.monotonic()
                        response = client.post(
                            "/agent/v2/chat",
                            json={"question": case["question"], "top_k": protocol["top_k"]},
                            headers={
                                "Authorization": f"Bearer {tokens[case['persona']]}",
                                "X-Request-ID": request_id,
                            },
                        )
                        payload = response.json()
                        trace = service.traces.get(request_id)
                        return dict(
                            kind=kind,
                            repeat=repeat,
                            profile=arm,
                            case_id=case["case_id"],
                            category=case["category"],
                            http_status=response.status_code,
                            client_ms=(time.perf_counter() - started) * 1000,
                            started_monotonic=request_started_monotonic,
                            response=payload,
                            server_trace=trace.model_dump(mode="json") if trace else None,
                            score=score_response(
                                case, response.status_code, payload, snapshots[case["version"]]
                            ),
                        )

                    if repeat == 0:
                        for warm in range(protocol["warmups_per_profile"]):
                            row = request(protocol["cases"][0], "warmup", warm)
                            warmups.append(row)
                            append(row)
                    for ordinal, case in enumerate(protocol["cases"]):
                        if load_active_pointer(indexes).run_id != case["version"]:
                            activate_version(indexes, case["version"])
                        row = request(case, "main", ordinal)
                        rows.append(row)
                        append(row)
                        print(
                            json.dumps(
                                {
                                    "completed": len(rows),
                                    "profile": arm,
                                    "repeat": repeat,
                                    "case_id": case["case_id"],
                                    "mode": row["response"].get("mode"),
                                    "contract": row["score"]["contract_complete"],
                                    "ms": round(row["client_ms"]),
                                }
                            ),
                            flush=True,
                        )
                        if row["score"]["known_security_failure"]:
                            raise RuntimeError(
                                "known publication/security contract failed; "
                                "retained rows require diagnosis"
                            )
                    if repeat == 2:
                        activate_version(indexes, "base")
                        for concurrency in protocol["concurrency_points"]:
                            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                                measured = list(
                                    pool.map(
                                        lambda i, concurrency=concurrency: request(
                                            protocol["cases"][0], f"resource{concurrency}", i
                                        ),
                                        range(protocol["resource_requests_per_point"]),
                                    )
                                )
                            for row in measured:
                                row["concurrency"] = concurrency
                                resources.append(row)
                                append(row)
                                if row["score"]["known_security_failure"]:
                                    raise RuntimeError("resource probe failed security contract")
                (args.output / "progress.json").write_text(
                    json.dumps({"completed": len(rows), "last_block": block}), encoding="utf8"
                )
    final = source_identity()
    if (
        final["app_sources_sha256"] != initial["app_sources_sha256"]
        or final["harness_sha256"] != initial["harness_sha256"]
    ):
        raise RuntimeError("execution code changed; cannot certify run")
    if len(rows) != protocol["main_requests"]:
        raise RuntimeError("incomplete cohort")
    expected_warmups = 5 * len(protocol["profiles"])
    expected_resources = (
        len(protocol["profiles"])
        * len(protocol["concurrency_points"])
        * protocol["resource_requests_per_point"]
    )
    if len(warmups) != expected_warmups or len(resources) != expected_resources:
        raise RuntimeError("incomplete warmup or resource protocol")
    import numpy as np

    summary = []
    for profile in protocol["profiles"]:
        selected = [row for row in rows if row["profile"] == profile]
        timing = [row["client_ms"] for row in selected]
        summary.append(
            dict(
                profile=profile,
                n=len(selected),
                first_pass_complete=sum(
                    row["score"]["contract_complete"] for row in selected if row["repeat"] == 0
                ),
                all_pass_complete=sum(row["score"]["contract_complete"] for row in selected),
                mode_counts=dict(
                    __import__("collections").Counter(
                        row["response"].get("mode", f"http_{row['http_status']}")
                        for row in selected
                    )
                ),
                mean_ms=float(np.mean(timing)),
                p50_ms=float(np.percentile(timing, 50)),
                p95_ms=float(np.percentile(timing, 95)),
            )
        )
    result = dict(
        kind="SYNTHETIC_AUTOMATIC_CONTRACT_NOT_HUMAN_ACCURACY",
        summary=summary,
        startup=startup,
        main_count=len(rows),
        warmup_count=len(warmups),
        resource_count=len(resources),
        resource_samples=sampler.samples,
        rows_sha256=sha(args.output / "rows.jsonl"),
    )
    (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    (args.output / "completion.json").write_text(
        json.dumps(
            dict(
                status="COMPLETE",
                source_unchanged=True,
                source=final,
                summary_sha256=sha(args.output / "summary.json"),
                rows_sha256=result["rows_sha256"],
            ),
            indent=2,
        ),
        encoding="utf8",
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
