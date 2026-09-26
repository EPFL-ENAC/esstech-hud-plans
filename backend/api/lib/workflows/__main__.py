from api.config import config
from api.lib.workflows.splat_generation import splat_generation_flow
from api.lib.workflows.uploads_cleanup import purge_expired_upload_sessions


def serve_workflows() -> None:
    splat_generation_flow.serve(name="default", limit=1)
    purge_expired_upload_sessions.serve(
        interval=config.UPLOAD_CLEANUP_INTERVAL_MINUTES * 60
    )


if __name__ == "__main__":
    serve_workflows()
