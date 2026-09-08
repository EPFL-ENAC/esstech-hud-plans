from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import warning

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from pydantic import BaseModel

from api.config import config
from api.db import dispose_engine
from api.logging_config import setup_logging
from api.views.admin import router as admin_router
from api.views.auth import router as auth_router
from api.views.buildings import router as buildings_router
from api.views.reconstructions import router as reconstructions_router
from api.views.splats import router as splats_router
from api.views.users import router as users_router
from api.views.workflows import router as workflows_router

# from api.views.files import router as files_router


setup_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
    try:
        yield
    finally:
        await dispose_engine()


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
    expose_headers=["Accept-Ranges", "Content-Range"],
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
    auth_router,
    prefix="/auth",
    tags=["Auth"],
)

app.include_router(
    splats_router,
    prefix="/splats",
    tags=["Splats"],
)

app.include_router(
    workflows_router,
    prefix="/workflows",
    tags=["Workflows"],
)

app.include_router(
    buildings_router,
    prefix="/buildings",
    tags=["Buildings"],
)

app.include_router(
    users_router,
    prefix="/user",
    tags=["Users"],
)

app.include_router(
    reconstructions_router,
    prefix="/buildings/{building_id}/reconstructions",
    tags=["Reconstructions"],
)

app.include_router(
    admin_router,
    prefix="/admin",
    tags=["Admin"],
)
