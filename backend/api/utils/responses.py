import logging
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)


@contextmanager
def file_storage_errors(path: Path) -> Iterator[None]:
    """Translate filesystem errors during response preparation into HTTP errors."""
    try:
        yield
    except (FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except OSError as exc:
        logger.exception("Failed to access file storage at %s", path)
        raise HTTPException(
            status_code=503,
            detail="File storage is unavailable",
        ) from exc


def inline_file_response(
    path: Path,
    *,
    root_directory: Path,
    media_type: str,
) -> FileResponse:
    """Serve a readable file within a trusted, absolute directory boundary.

    Callers must wrap response preparation in file_storage_errors() to translate
    filesystem exceptions into HTTP responses.
    """
    # Preserve the trusted boundary: resolving it would allow a symlink
    # replacing root_directory to expand access outside that directory.
    resolved_path = path.resolve(strict=True)
    if not resolved_path.is_relative_to(root_directory):
        raise HTTPException(status_code=404, detail="File not found")

    file_stat = resolved_path.stat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise HTTPException(status_code=404, detail="File not found")

    # Detect access errors before FileResponse sends response headers.
    with resolved_path.open("rb"):
        pass

    return FileResponse(
        path=resolved_path,
        stat_result=file_stat,
        media_type=media_type,
        filename=resolved_path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
