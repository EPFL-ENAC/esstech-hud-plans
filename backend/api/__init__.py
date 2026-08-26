import os

from api.config import config

os.environ.setdefault("PREFECT_API_URL", config.PREFECT_API_URL)
import prefect  # noqa: F401  (must be imported after setting PREFECT_API_URL)
