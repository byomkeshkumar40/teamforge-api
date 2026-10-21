from dataclasses import dataclass

from pydantic import BaseModel

# PostgreSQL text cannot hold U+0000; reject it at the edge instead of failing with a 500.
NO_NUL = r"^[^\x00]*$"

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
