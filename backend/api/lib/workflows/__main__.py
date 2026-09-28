from api.lib.workflows.splat_generation import splat_generation_flow
from api.lib.workflows.tus_cleanup import tus_cleanup_flow


def serve_workflows() -> None:
    splat_generation_flow.serve(name="default", limit=1)
    tus_cleanup_flow.serve(name="tus-cleanup", interval=86400, limit=1)


if __name__ == "__main__":
    serve_workflows()
