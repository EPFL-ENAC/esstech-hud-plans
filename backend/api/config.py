from functools import lru_cache

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    PATH_PREFIX: str = ""
    APP_URL: str = "http://localhost:9000"

    MIN_COLMAP_IMAGES_KEEP: int = 20


@lru_cache()
def get_config():
    return Config()


config = get_config()
