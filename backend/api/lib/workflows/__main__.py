from prefect import serve

from api.lib.workflows.splat_generation import splat_generation_flow
from api.lib.workflows.tus_cleanup import tus_cleanup_flow


def serve_workflows() -> None:
    reconstruction = splat_generation_flow.to_deployment(
        name="default",
        concurrency_limit=1,
    )
    cleanup = tus_cleanup_flow.to_deployment(
        name="tus-cleanup",
        interval=86400,
        concurrency_limit=1,
    )

    serve(reconstruction, cleanup, limit=2)


if __name__ == "__main__":
    serve_workflows()
