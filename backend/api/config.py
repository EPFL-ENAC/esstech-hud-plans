from functools import lru_cache

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    PATH_PREFIX: str = ""
    APP_URL: str = "http://localhost:9000"

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


@lru_cache()
def get_config():
    return Config()


config = get_config()
