from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError, BaseModel
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.status import HTTP_201_CREATED

from app import rate_limits
from app.dependencies import get_current_actor, login_required, is_admin, get_sw
from app.middlewares import limiter
from app.models.orm import RegisteredActor
from app.models.schema.actor import ActorRegisterIn
from app.models.schema.domain_models import DomainLang
from app.models.schema.template_code_entry_schema import TemplateLang
from app.models.schema.response import ErrorResponse, GenResponse
from app.services.service_worker import ServiceWorker
from app.settings import env_settings
from app.util.controller_utils import delete_temp_file
from app.util.files import create_temp_csv, zip_files

router = APIRouter(
    prefix="/tests", tags=["Tests"], include_in_schema=env_settings().is_dev()
)


@router.get("/testy")
async def test_r(
    user_agent: Optional[str] = Header(None),
    r: Request = None,
    sw: ServiceWorker = Depends(get_sw),
    user: RegisteredActor = Depends(get_current_actor),
):
    # es = sw.entry.base_q().filter(Entry.is_creator(user)).all()
    # print(es)
    # print(user.editor_domain)
    # print(sw.db_session.query(RegisteredActor).filter(RegisteredActor.editor_for_domain("licci")).all())
    print(r.state.current_user)
    return "ok"


@router.get("/get_current_actor")
async def test_get_current_actor(user: RegisteredActor = Depends(get_current_actor)):
    if user:
        return user.registered_name


@router.get("/logged_in")
async def test_logged_in(user: RegisteredActor = Depends(login_required)):
    return user.registered_name


@router.get("/current_user_is_admin")
async def test_current_user_is_admin(user: RegisteredActor = Depends(is_admin)):
    return user.registered_name


@router.get("/current_user_is_admin")
async def test_current_user_is_admin(user: RegisteredActor = Depends(is_admin)):
    return user.registered_name


# @router.get("/test_template_or")
# async def test_template_or(
#         sw: ServiceWorker = Depends(get_sw),
#         user: RegisteredActor = Depends(get_current_actor)):
#     entries = entries_query_builder(
#         sw, user, entrytypes={TEMPLATE},
#         search_query=EntrySearchQueryIn(required=[
#             RequiredDefinition(name=LANGUAGE, value=["en"]),
#             RequiredDefinition(name=STATUS, value={PUBLISHED})],
#             include={
#                 "domain": ["licci"],
#                 "template": ["raw_observation"]
#             })
#     ).all()
#
#     entries = entries_query_builder(
#         sw, user, entrytypes={TEMPLATE, CODE},
#         search_query=EntrySearchQueryIn(required=[
#             RequiredDefinition(name=STATUS, value={PUBLISHED}),
#         ],
#             include={
#                 TEMPLATE: "raw_observation_licci"
#             })
#     ).all()
#
#     entries_out = [e.slug for e in entries]
#     return entries_out


@router.get("/domain_lang_out")
async def domain_lang_out(domain: str, sw: ServiceWorker = Depends(get_sw)):
    res = sw.domain.crud_read_dmetas_dlangs(["en"], [domain])
    # print(json.dumps(res[0].lang.content["map"]["layers"], indent=2))
    return DomainLang.from_orm(res[0].lang).dict(exclude_none=True)


@router.get("/entry_lang_out")
async def entry_lang_out(slug: str, sw: ServiceWorker = Depends(get_sw)):
    res = sw.template_codes.get_by_slug(slug, "en")
    # print(json.dumps(res.aspects[4]["list_items"]["components"][2], indent=2))
    try:
        return TemplateLang.from_orm(res).dict(exclude_none=True, exclude_unset=True)
    except ValidationError as err:
        print(err)
        return {}


@router.get("/entry_version")
async def entry_version(slug: str, version: int, sw: ServiceWorker = Depends(get_sw)):
    return sw.entry.get_version(
        sw.template_codes.get_base_schema_by_slug(slug), version
    )


"""
TEST ROUTES ARE TUPLICATES OF REAL ROUTES WITH SPECIAL PROPS
"""


@router.post(
    "/actor/",
    status_code=HTTP_201_CREATED,
    responses={
        409: {
            "model": ErrorResponse,
            # "description": LanguageServiceWorker(None, "en").t("actor.api.already_taken")
        }
    },
)
@limiter.limit(rate_limits.Actor.register)
async def register(
    actor: ActorRegisterIn,
    request: Request,
    sw: ServiceWorker = Depends(get_sw),
):
    """
    duplicate of POST actor/
    register a new user
    @param actor:
    @param request: just for the rate-limit plugin...
    @param sw:
    @return:
    """
    sw.actor.username_or_email_exists(
        actor.registered_name, actor.email, raise_error=True
    )
    db_actor: RegisteredActor = sw.actor.crud_create(actor)
    verification_code = None
    if env_settings().EMAIL_VERIFICATION_REQUIRED:
        # changed to get the code
        success, verification_code = sw.actor.make_send_actor_verification_code(
            db_actor
        )
    # add verification_code to response
    return GenResponse(
        msg=sw.t("actor.register_ok"), data={"verification_code": verification_code}
    )


@router.get("/zip_test/")
async def zip_test():
    temp_file = await create_temp_csv(["a", "b"], [{"a": 0, "b": 1}])
    temp_file.close()
    zip_file = await zip_files("fantastic.zip", [(temp_file, "somecool.csv")])
    return FileResponse(
        zip_file.filename,
        filename="fantastic.zip",
        background=BackgroundTask(delete_temp_file, file_path=zip_file.filename),
    )


@router.get("/error")
async def test_error_resp(sw: ServiceWorker = Depends(get_sw)):
    return sw.error_response(400, "actor.wrong_code")


class TestModel(BaseModel):
    start: int
    end: int


@router.delete("/delete_body")
async def test_error_resp(data: TestModel, sw: ServiceWorker = Depends(get_sw)):
    return data
