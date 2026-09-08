from typing import Annotated

from api.models.user import User, UserRead
from api.services.auth import require_user
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def get_current_user(
    current_user: Annotated[User, Depends(require_user)],
) -> User:
    """Return the persisted row synchronized from the current identity."""

    return current_user
