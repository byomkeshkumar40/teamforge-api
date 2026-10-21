from app.core.security import create_access_token
from app.models import User

TEST_PASSWORD = "Correct-Horse-9"


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
