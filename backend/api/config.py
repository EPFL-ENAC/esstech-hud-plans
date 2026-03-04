from functools import lru_cache

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    PATH_PREFIX: str = ""
    APP_URL: str = "http://localhost:9000"

    MIN_COLMAP_IMAGES_KEEP: int = 20

    USE_RUNAI: bool = False
    # RUNAI_API_URL: str = ""
    # RUNAI_CLUSTER_URL: str = ""
    # RUNAI_CLIENT_ID: str = ""
    # RUNAI_CLIENT_SECRET: str = ""
    # RUNAI_PROJECT: str = ""
    RUNAI_REGISTRY: str = ""
    # RUNAI_PVC_HOME_PATH: str = ""
    RUNAI_PVC_SCRATCH_NAME: str = ""
    RUNAI_MOUNT_SCRATCH_PATH: str = ""


@lru_cache()
def get_config():
    return Config()


config = get_config()
