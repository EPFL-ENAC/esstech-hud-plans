import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from api.db import get_session
from api.models.user import User, UserRead
from api.services.auth import require_user
from api.services.users import UserService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserService:
    """Build a request-scoped user service."""

    return UserService(session)


@router.get("/me", response_model=UserRead)
async def get_current_user(
    current_user: Annotated[User, Depends(require_user)],
) -> User:
    """Return the persisted row synchronized from the current identity."""

    return current_user


@router.delete("/me/data", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user_data(
    current_user: Annotated[User, Depends(require_user)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> None:
    """Delete every building, reconstruction, artifact, and the user row."""

    try:
        await users.delete_all_data(current_user)
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("User data deletion failed", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User database is unavailable",
        ) from exc
