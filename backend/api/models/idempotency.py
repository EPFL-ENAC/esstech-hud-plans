from enum import StrEnum
from uuid import UUID

from sqlalchemy import Column, Enum
from sqlmodel import Field, SQLModel


class IdempotencyStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"


class IdempotencyRecords(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "idempotency_records"

    owner_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        primary_key=True,
    )
    idempotency_key: str = Field(primary_key=True)
    status: IdempotencyStatus = Field(
        default=IdempotencyStatus.STARTED,
        sa_column=Column(
            Enum(
                IdempotencyStatus,
                name="idempotency_status",
                values_callable=lambda statuses: [status.value for status in statuses],
            ),
            nullable=False,
        ),
    )
