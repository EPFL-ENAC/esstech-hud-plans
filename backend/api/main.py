from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import INFO, Formatter, StreamHandler, basicConfig, getLogger, warning

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from pydantic import BaseModel

from api.config import config
from api.views.admin import router as admin_router
from api.views.splats import router as splats_router

# from api.views.files import router as files_router


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


setup_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
    yield


app = FastAPI(root_path=config.PATH_PREFIX, lifespan=lifespan)

origins = [config.APP_URL] if config.APP_URL else []
if not config.APP_URL:
    warning(
        "config.APP_URL is not set. CORS will not allow any origins. "
        "Set config.APP_URL to enable cross-origin requests."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthCheck(BaseModel):
    """Response model to validate and return when performing a health check."""

    status: str = "OK"


@app.get(
    "/healthz",
    tags=["Healthcheck"],
    summary="Perform a Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
    response_model=HealthCheck,
)
async def get_health() -> HealthCheck:
    """Endpoint to perform an API healthcheck."""

    return HealthCheck(status="OK")


app.include_router(
    splats_router,
    prefix="/splats",
    tags=["Splats"],
)

app.include_router(
    admin_router,
    prefix="/admin",
    tags=["Admin"],
)
