from pydantic import BaseModel


class Page[T](BaseModel):
    """A slice of results and the total number of matching records."""

    items: list[T]
    total: int
