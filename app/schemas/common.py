from dataclasses import dataclass

from pydantic import BaseModel

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
