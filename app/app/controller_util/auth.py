from typing import Optional

from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.models.orm.registered_actor_orm import RegisteredActor
from app.models.orm.token import Token
from app.util.consts import VISITOR

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/actor/token_login", auto_error=False
)


def get_actor_by_auth_token(
    db_session: Session, auth_token: Optional[str]
) -> Optional[RegisteredActor]:
    if not auth_token:
        return None
    token = (
        db_session.query(Token).filter(Token.access_token == auth_token).one_or_none()
    )
    if token:
        return token.actor
    else:
        return None


def session_not_user(user_name: Optional[str]) -> bool:
    return not user_name or user_name == VISITOR


def actor_not_user(user: Optional[RegisteredActor]) -> bool:
    return not user or user.is_visitor
