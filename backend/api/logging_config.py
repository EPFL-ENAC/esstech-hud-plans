"""Central logging configuration shared by the API and background workers."""

from logging import INFO, Formatter, StreamHandler, basicConfig, getLogger


def setup_logging():
    """Configure logging handlers for uvicorn and application loggers."""
    handler = StreamHandler()
    handler.setLevel(INFO)
    handler.setFormatter(
        Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    basicConfig(level=INFO, handlers=[handler], force=True)

    uvicorn_logger = getLogger("uvicorn")
    uvicorn_logger.setLevel(INFO)
    uvicorn_logger.handlers = [handler]
    uvicorn_logger.propagate = False

    uvicorn_error_logger = getLogger("uvicorn.error")
    uvicorn_error_logger.setLevel(INFO)
    uvicorn_error_logger.handlers = [handler]
    uvicorn_error_logger.propagate = False

    uvicorn_access_logger = getLogger("uvicorn.access")
    uvicorn_access_logger.setLevel(INFO)
    uvicorn_access_logger.handlers = [handler]
    uvicorn_access_logger.propagate = False
