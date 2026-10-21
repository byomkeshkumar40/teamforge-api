from enum import StrEnum


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so user input is matched literally (use with escape="\\")."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
