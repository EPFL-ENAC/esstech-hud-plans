from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.config import config
from api.models.user import User, UserRead
from api.services.auth import get_user_service, require_user_not_accepted
from api.services.terms import is_accepted, terms_content
from api.services.users import UserService

router = APIRouter()


class TermsContentRead(BaseModel):
    """Terms markdown keyed by locale."""

    en: str
    fr: str
    es: str


class TermsRead(BaseModel):
    """Current terms version and its per-locale content."""

    version: str
    content: TermsContentRead


@router.get("", response_model=TermsRead)
async def get_terms(
    current_user: Annotated[User, Depends(require_user_not_accepted)],
) -> TermsRead:
    """Return the current terms version and content in every locale."""

    return TermsRead(
        version=config.TERMS_VERSION,
        content=TermsContentRead(**terms_content()),
    )


@router.post("/accept", response_model=UserRead)
async def accept_terms(
    current_user: Annotated[User, Depends(require_user_not_accepted)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> UserRead:
    """Record acceptance of the current terms for the current user."""

    updated = await users.accept_terms(current_user)
    return UserRead(**updated.model_dump(), terms_accepted=is_accepted(updated))
