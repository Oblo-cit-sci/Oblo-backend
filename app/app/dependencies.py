from typing import Optional, TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from app.controller_util.auth import oauth2_scheme, get_actor_by_auth_token
from app.models.orm import RegisteredActor
from app.models.schema import EntryMainModel
from app.util.consts import UUID, SLUG, LANGUAGE

from app.util.exceptions import ApplicationException

from app.services.service_worker import ServiceWorker


def get_db(request: Request):
    return request.state.db


def get_current_actor(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db_session: Session = Depends(get_db),
) -> Optional[RegisteredActor]:
    token_actor = get_actor_by_auth_token(db_session, token)
    if token_actor:
        return token_actor
    else:
        if request.session.get("user"):
            actor = (
                db_session.query(RegisteredActor)
                .filter(RegisteredActor.registered_name == request.session.get("user"))
                .one_or_none()
            )
            request.state.current_user = actor
            # TODO insert visitor if not defined:
            # this visitor is added on setup...
            # return request.app.state.visitor
            return actor


def login_required(
    request: Request, actor=Depends(get_current_actor)
) -> Optional[RegisteredActor]:
    if not actor:
        raise ApplicationException(
            HTTP_401_UNAUTHORIZED,
            msg="You must be logged in",
            data={"logged_in": False},
        )
    return actor


def is_admin(user: RegisteredActor = Depends(login_required)) -> RegisteredActor:
    if not user.is_admin:
        raise ApplicationException(HTTP_403_FORBIDDEN, msg="You must be admin")
    return user


def get_sw(request: Request, actor=Depends(get_current_actor)) -> ServiceWorker:
    request.state.current_actor = actor
    return request.state.service_worker


# this is a dependency method
# todo: maybe indicate dependency methods in the name and put them all in one place
def get_current_entry(
    request: Request, sw: ServiceWorker = Depends(get_sw)
) -> EntryMainModel:
    params = {**request.path_params, **request.query_params}
    # todo following is basic the EntryRef resolver
    uuid = params.get(UUID)

    entry = None
    # logger.warning(request.query_params)
    # todo use general purpose entry-resolver
    if uuid:
        entry = sw.entry.crud_get(uuid)

    slug = params.get(SLUG)
    language = params.get(LANGUAGE)
    if slug:
        if language:
            entry = sw.template_codes.get_by_slug_lang(slug, language)
        else:
            entry = sw.template_codes.get_base_schema_by_slug(slug)
    if not entry:
        raise ApplicationException(
            404, "no entry found", {"uuid": uuid, "slug": slug, "language": language}
        )
    entry_model = sw.entry.to_model(entry, sw.entry.get_model_type(entry), True)

    sw.state.current_entry = entry_model

    sw.state.current_db_entry = entry
    return entry_model
