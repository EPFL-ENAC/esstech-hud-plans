import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    PATH_PREFIX: str = ""
    APP_URL: str = "http://localhost:9000"

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "postgres"
    DB_USER: str
    DB_PASSWORD: str

    @property
    def DB_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    PREFECT_HOST: str = "localhost"
    PREFECT_PORT: int = 4200

    KEYCLOAK_ENDPOINT: str = "https://enac-it-sso2.epfl.ch"
    KEYCLOAK_REALM: str = "external"
    KEYCLOAK_CLIENT_ID: str = "esstech-poh"
    KEYCLOAK_CLIENT_SECRET: str = ""

    # Root directory for workflow data, absolute or relative to backend directory
    # When USE_SCITAS is true, set DATA_DIR to the same value as SCITAS_MOUNT_EXPORT_PATH
    DATA_DIR: str = "data"

    @property
    def DATA_PATH(self) -> Path:
        path = Path(self.DATA_DIR)
        return (
            path if path.is_absolute() else Path(__file__).resolve().parents[1] / path
        )

    @property
    def PREFECT_API_URL(self) -> str:
        return f"http://{self.PREFECT_HOST}:{self.PREFECT_PORT}/api"

    MIN_COLMAP_IMAGES_KEEP: int = 20

    USE_RUNAI: bool = False
    RUNAI_REGISTRY: str = ""
    RUNAI_PVC_SCRATCH_NAME: str = ""
    RUNAI_MOUNT_SCRATCH_PATH: str = ""

    USE_SCITAS: bool = False
    SCITAS_MOUNT_EXPORT_PATH: str = "/mnt/scitas"
    SCITAS_REMOTE_EXPORT_PATH: str = "/export/enac-it-poh"
    SCITAS_REMOTE_SCRATCH_PATH: str = "/scratch/enac-it-poh"
    SCITAS_REMOTE_IMAGES_PATH: str = "/work/enac-it-poh/apptainer-images"
    SCITAS_HOST: str = "kuma.hpc.epfl.ch"
    SCITAS_ACCOUNT: str = "enac-it-poh"
    SCITAS_SSH_USERNAME: str = "enac-it-poh"
    SCITAS_SSH_KEY_PATH: str = "~/.ssh/id_ed25519"
    SCITAS_PARTITION_DEFAULT: str = "l40s"
    SCITAS_PARTITION_COLMAP: str = "l40s"  # could be mig24gb but less availability
    SCITAS_PARTITION_BRUSH: str = "l40s"
    SCITAS_SBATCH_ARGS_COLMAP: str = ""
    SCITAS_SBATCH_ARGS_BRUSH: str = ""

    # Host directory where the tusd container stores upload chunks and .info files.
    # Bind-mounted into the tusd container. Must stay on a local disk
    # (tusd needs hard links; never on the SCITAS mount).
    TUSD_UPLOAD_DIR: str = "/tmp/hud-tusd-uploads"
    # Age threshold for the tus cleanup flow
    TUSD_UPLOAD_RETENTION_DAYS: int = 7
    # Hook endpoint URL tusd calls for pre-create validation (used by the compose command)
    TUSD_HOOKS_HTTP_URL: str = "http://host.docker.internal:8000/tus/hooks"
    # Internal address of the tusd server. The API proxies upload requests to
    # it, so the browser never reaches tusd. Dev targets the loopback-published
    # compose port. In the real deployment tusd is not exposed and this points
    # at the compose service (http://tusd:8080)
    TUSD_INTERNAL_URL: str = "http://localhost:8080"


@lru_cache()
def get_config():
    return Config()


config = get_config()
