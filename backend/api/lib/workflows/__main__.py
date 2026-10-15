from prefect import serve

from api.config import config
from api.lib.workflows.splat_generation import splat_generation_flow
from api.lib.workflows.tus_cleanup import tus_cleanup_flow


def serve_workflows() -> None:
    reconstruction = splat_generation_flow.to_deployment(
        name="default",
        concurrency_limit=config.PREFECT_SPLAT_GENERATION_CONCURRENCY,
    )
    cleanup = tus_cleanup_flow.to_deployment(
        name="tus-cleanup",
        interval=86400,
        concurrency_limit=config.PREFECT_TUS_CLEANUP_CONCURRENCY,
    )

    # Runner-wide cap; the sum keeps both per-flow limits reachable
    serve(
        reconstruction,
        cleanup,
        limit=config.PREFECT_SPLAT_GENERATION_CONCURRENCY
        + config.PREFECT_TUS_CLEANUP_CONCURRENCY,
    )


if __name__ == "__main__":
    serve_workflows()
