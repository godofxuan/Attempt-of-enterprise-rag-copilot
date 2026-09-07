"""API factory with opt-in reranker startup readiness.

Run with uvicorn app.serving:create_app --factory --workers 1.
The original application, authentication and lifespan are retained intact.
"""

from contextlib import asynccontextmanager
from dataclasses import replace

from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.main import create_app as create_base_app
from app.retrieval.local_cross_encoder import get_local_cross_encoder
from app.retrieval.serving_config import ServingRetrievalSettings
from app.runtime.resources import build_service_container
from app.runtime.serving_resources import ServingRuntimeResources


def create_app(container=None):
    if container is None:
        container = build_service_container(get_settings())
    # Preserve injected test/custom resource providers. Production uses the
    # same probes, with model inference restricted to initial validation.
    from app.runtime.resources import RuntimeResources

    if type(container.resources) is RuntimeResources:

        def identity_probe():
            container.identity_verifier.ready()
            container.feedback_actor_hasher.ready()

        resources = ServingRuntimeResources(
            container.settings,
            identity_probe=identity_probe,
            database_content_digest=container.feedback_actor_hasher.content_digest,
        )
        container = replace(container, resources=resources)
    application = create_base_app(container)
    original_lifespan = application.router.lifespan_context
    configuration = ServingRetrievalSettings()

    @asynccontextmanager
    async def lifespan(app):
        if configuration.retrieval_profile.startswith("safe_dense_raw"):
            scorer = get_local_cross_encoder(
                str(configuration.reranker_path.resolve()), configuration.reranker_device
            )
            await run_in_threadpool(scorer.warmup)
        async with original_lifespan(app):
            yield

    application.router.lifespan_context = lifespan
    return application
