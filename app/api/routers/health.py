from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: the process is up. Does not touch the database."""
    return {"status": "ok"}
