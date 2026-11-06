import asyncio

from prefect.runner import Runner

from api.config import config
from api.lib.workflows.splat_generation import splat_generation_flow
from api.lib.workflows.tus_cleanup import tus_cleanup_flow


async def serve_workflows() -> None:
    runner = Runner(
        pause_on_shutdown=False,
        limit=config.PREFECT_SPLAT_GENERATION_CONCURRENCY
        + config.PREFECT_TUS_CLEANUP_CONCURRENCY,
    )
    # Keep the flow objects available so cancellation hooks need no reload.
    await runner.aadd_flow(
        splat_generation_flow,
        name="default",
        concurrency_limit=config.PREFECT_SPLAT_GENERATION_CONCURRENCY,
    )
    await runner.aadd_flow(
        tus_cleanup_flow,
        name="tus-cleanup",
        interval=86400,
        concurrency_limit=config.PREFECT_TUS_CLEANUP_CONCURRENCY,
    )

    await runner.start()


if __name__ == "__main__":
    asyncio.run(serve_workflows())
