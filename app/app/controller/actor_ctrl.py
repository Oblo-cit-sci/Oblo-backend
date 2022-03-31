from logging import getLogger
from os.path import isfile, join
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin

from PIL.Image import Image
from fastapi import APIRouter, Depends, File, Query, UploadFile, Header
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy.orm.attributes import flag_modified
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_503_SERVICE_UNAVAILABLE,
    HTTP_201_CREATED, HTTP_422_UNPROCESSABLE_ENTITY,
)

from app import settings, rate_limits
from app.controller.entries_ctrl import entries_query
from app.dependencies import get_current_actor, login_required, is_admin, get_sw
from app.middlewares import limiter
from app.models.orm import Token
from app.models.orm.registered_actor_orm import RegisteredActor
from app.models.schema import (
    ActorBase,
    ActorSearchQuery,
    EntrySearchQueryIn,
    SearchValueDefinition,
    EntryMeta,
)
from app.models.schema.actor import (
    ActorAuthToken,
    ActorCredentialsIn,
    ActorLoginOut,
    ActorOut,
    ActorPasswordResetIn,
    ActorPasswordUpdateIn,
    ActorRegisterIn,
    ActorSearchOut,
    ActorSimpleOut,
    ActorUpdateIn,
    ActorEmailUpdateIn,
    EditorConfig,
)
from app.models.schema.response import (
    GenResponse,
    ErrorResponse,
    simple_message_response,
)
from app.services.service_worker import ServiceWorker
from app.services.util.image_edit import to_pil_image
from app.settings import env_settings
from app.util.consts import (
    ACTOR,
    EMAIL_VERIFICATION_CODE,
    PASSWORD_RESET_CODE,
    EDITOR,
    GLOBAL_ROLE,
    EDITOR_CONFIG,
)
from app.util.emails import send_password_reset_email
from app.util.exceptions import ApplicationException
from app.util.passwords import obscure_email_address, verify_hash

router = APIRouter(prefix="/actor", tags=["Actor"])

logger = getLogger(__name__)


@router.post(
    "/",
    response_model=simple_message_response,
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
) -> simple_message_response:
    """
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
    email_sent = False
    if env_settings().EMAIL_VERIFICATION_REQUIRED:
        email_sent = True
        sw.actor.make_send_actor_verification_code(db_actor)
    return sw.msg_data_response(msg="actor.register_ok", data={"email_sent": email_sent})


@router.get("/init_delete")
async def delete_account(
        sw: ServiceWorker = Depends(get_sw), current_actor=Depends(login_required)
):
    entries = sw.actor.get_delete_init_entries(current_actor)
    return sw.data_response(
        data={"entries": sw.entry.create_entry_list(entries, current_actor, EntryMeta)}
    )


@router.delete("/", response_model=simple_message_response)
async def delete_account(
        actor_credentials: ActorCredentialsIn,
        sw: ServiceWorker = Depends(get_sw),
        current_actor=Depends(login_required),
):
    if actor_credentials.registered_name != current_actor.registered_name:
        raise ApplicationException(
            HTTP_403_FORBIDDEN, sw.messages.t("actor.wrong_credentials")
        )
    sw.actor.verify_credentials(actor_credentials)
    sw.actor.delete(current_actor, [])
    return sw.msg_response("actor.unregister_ok")


@router.get("/validate_session")  # , response_model=SessionValidation)
async def validate_session(
        current_actor: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    resp = {"session_valid": current_actor is not None}
    if current_actor:
        actor_out: ActorOut = ActorOut.from_orm(current_actor)
        actor_out.config_share = sw.actor.add_config_share(current_actor)
        resp["data"] = actor_out
    return resp


@router.get("/me", response_model=ActorOut)
async def read_me(current_actor: RegisteredActor = Depends(login_required)):
    return ActorOut.from_orm(current_actor)


@router.post("/me")
async def update_profile(
        actor_in: ActorUpdateIn,
        sw: ServiceWorker = Depends(get_sw),
        current_actor: RegisteredActor = Depends(login_required),
) -> GenResponse[ActorOut]:
    """
    used for updating the profile and settings
    """
    sw.actor.crud_update(current_actor, actor_in)
    actor_out = ActorOut.from_orm(current_actor)
    actor_out.config_share = sw.actor.add_config_share(current_actor)
    return sw.msg_data_response(data=actor_out, msg="actor.profile_updated")


@router.post("/change_email")
async def change_email(
        email_change_in: ActorEmailUpdateIn,
        sw: ServiceWorker = Depends(get_sw),
        current_actor: RegisteredActor = Depends(login_required),
):
    sw.actor.change_email(current_actor, email_change_in)
    return sw.msg_response("actor.email_change")


@router.post("/change_password", response_model=simple_message_response)
async def change_password(
        actor_pwd_in: ActorPasswordUpdateIn,
        sw: ServiceWorker = Depends(get_sw),
        current_actor: RegisteredActor = Depends(login_required),
):
    sw.actor.change_password(current_actor, actor_pwd_in)
    return sw.msg_response("actor.password_change")


@router.get("/{registered_name}/avatar")
async def get_avatar(
        registered_name: str, _: str = "", sw: ServiceWorker = Depends(get_sw)
):
    # q is not used, only for the browser, to change the URL and force a reload
    actor_avatar_path = join(sw.actor.get_actor_path(registered_name), "avatar.jpg")
    if isfile(actor_avatar_path):
        return FileResponse(actor_avatar_path)
    else:
        return RedirectResponse("/api/actor/visitor/avatar")


@router.get("/{registered_name}/profile_pic")
async def get_profile_pic(
        registered_name: str, _: str = "", sw: ServiceWorker = Depends(get_sw)
):
    # q is not used, only for the browser, to change the URL and force a reload
    actor_avatar_path = join(sw.actor.get_actor_path(registered_name), "profile.jpg")
    if isfile(actor_avatar_path):
        return FileResponse(actor_avatar_path)
    else:
        return FileResponse(join(settings.COMMON_DATA_FOLDER, "avatar.jpg"))


@router.post("/login")
@limiter.limit(rate_limits.Actor.login)
async def login(
        request: Request,
        user_agent: Optional[str] = Header(None),
        form_data: OAuth2PasswordRequestForm = Depends(),
        sw: ServiceWorker = Depends(get_sw),
):
    # username is username_or_password but OAuth2PasswordRequestForm only has username
    email_or_username = form_data.username.lower()
    actor = sw.actor.find_by_email_or_username(email_or_username)
    if not actor:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST,
            msg=sw.messages.t("actor.account_not_found"),
        )

    if not actor.email_validated and env_settings().EMAIL_VERIFICATION_REQUIRED:
        raise ApplicationException(
            401,
            sw.messages.t("actor.verification_incomplete"),
            data={"error_type": 1, "registered_name": actor.registered_name},
        )

    sw.actor.login(actor, form_data.password, request)
    actor_out: ActorOut = ActorOut.from_orm(actor)
    actor_out.config_share = sw.actor.add_config_share(actor)
    return sw.msg_data_response(
        data=actor_out, msg="actor.login_ok", language=actor.settings["ui_language"]
    )


@router.post("/token_login")
@limiter.limit(rate_limits.Actor.token_login)
async def token_login(
        request: Request,
        user_agent: Optional[str] = Header(None),
        form_data: OAuth2PasswordRequestForm = Depends(),
        sw: ServiceWorker = Depends(get_sw),
):
    # username is username_or_password but OAuth2PasswordRequestForm only has username
    email_or_username = form_data.username.lower()
    actor = sw.actor.find_by_email_or_username(email_or_username)
    if not actor:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST,
            msg=sw.messages.t("actor.account_not_found"),
        )

    if not actor.email_validated and env_settings().EMAIL_VERIFICATION_REQUIRED:
        raise ApplicationException(
            401,
            sw.messages.t("actor.verification_incomplete"),
            data={"error_type": 1, "registered_name": actor.registered_name},
        )

    try:
        credentials = ActorCredentialsIn(
            registered_name=actor.registered_name,
            password=form_data.password
        )
    except ValidationError as err:

        raise ApplicationException(
            HTTP_422_UNPROCESSABLE_ENTITY,
            msg=sw.messages.t("actor.wrong_credentials"),
            data={"validation_data": err.errors()},
        )
    actor__auth_token: Tuple[RegisteredActor, Token] = sw.actor.token_login(user_agent, credentials, request)

    auth_stuff = ActorAuthToken.from_orm(actor__auth_token[1]).dict()
    actor_out_schema = ActorLoginOut.construct(
        user={
            **ActorOut.from_orm(actor__auth_token[0]).dict(),
            "config_share": sw.actor.add_config_share(actor),
        },
        **auth_stuff,
    )
    return {
        "data": actor_out_schema,
        "msg": sw.messages.t("actor.login_ok", actor.settings["ui_language"]),
        **auth_stuff,
    }


@router.get("/validate_token")  # not used by the FE
async def validate_session(
        current_actor: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    resp = {"session_valid": current_actor is not None}
    if current_actor:
        actor_out: ActorOut = ActorOut.from_orm(current_actor)
        actor_out.config_share = sw.actor.add_config_share(current_actor)
        resp["data"] = actor_out
    return resp


@router.get("/logout", response_model=simple_message_response)
async def actor_logout(
        request: Request,
        current_actor: RegisteredActor = Depends(login_required),
        sw: ServiceWorker = Depends(get_sw),
):
    sw.actor.logout(current_actor, request)
    return sw.msg_response("actor.logout_ok")


@router.post("/profile_pic", response_model=simple_message_response)
async def post_profile_pic(
        file: UploadFile = File(...),
        current_actor: RegisteredActor = Depends(login_required),
        sw: ServiceWorker = Depends(get_sw),
):
    if not file.content_type.startswith("image"):
        logger.debug(f"content_type: {file.content_type}, file: {file}")
        raise ApplicationException(
            HTTP_400_BAD_REQUEST, sw.messages.t("actor.wrong_content_type")
        )
    else:
        sw.actor.create_user_folder(current_actor)
        img: Image = to_pil_image(file)
        actor_path = sw.actor.get_actor_path(current_actor.registered_name)
        img.thumbnail((512, 512))
        img.save(actor_path + "/profile.jpg")
        img.thumbnail((128, 128))
        img.save(actor_path + "/avatar.jpg")
        return sw.msg_response("actor.image_upload")


@router.post("/search", response_model=GenResponse[List[ActorSearchOut]])
async def actor_search(
        search_config: ActorSearchQuery, sw: ServiceWorker = Depends(get_sw)
):
    return sw.data_response(sw.actor.search(search_config))


@router.get(
    "/{registered_name}/basic",
    response_model=GenResponse[ActorSimpleOut],
    dependencies=[Depends(get_current_actor)],
)
async def get_basic_info(registered_name: str, sw: ServiceWorker = Depends(get_sw)):
    of_actor = sw.actor.crud_read(registered_name)

    actor_out = ActorSimpleOut.from_orm(of_actor)
    if of_actor.global_role == EDITOR:
        actor_out.editor_config = sw.actor.get_config(of_actor, EDITOR_CONFIG)
    return sw.data_response(actor_out)


# not used by the FE anymore
@router.get("/{registered_name}/entries")
async def get_actor_entries(
        registered_name: str,
        sw: ServiceWorker = Depends(get_sw),
        current_actor: RegisteredActor = Depends(get_current_actor),
        limit: int = Query(20, ge=0, le=100),
        offset: int = Query(0, ge=0),
):
    return await entries_query(
        search_query=EntrySearchQueryIn(
            required=[SearchValueDefinition(name=ACTOR, value=registered_name)]
        ),
        sw=sw,
        current_actor=current_actor,
        limit=limit,
        offset=offset,
    )


@router.post("/{registered_name}/admin/global_role", dependencies=[Depends(is_admin)])
async def change_global_role(
        registered_name: str,
        editor_config: EditorConfig,
        sw: ServiceWorker = Depends(get_sw),
) -> simple_message_response:
    db_actor: RegisteredActor = sw.actor.crud_read(registered_name)
    # could delete global_role column if we now how to work with jsonb properly :)
    db_actor.global_role = editor_config.global_role
    # what is this exclude for?!
    sw.actor.edit_configs(
        db_actor, add={EDITOR_CONFIG: editor_config.dict(exclude={GLOBAL_ROLE})}
    )
    flag_modified(db_actor, "configs")
    sw.db_session.commit()
    return sw.msg_response("actor.role_change")


@router.get(
    "/get_all",
    response_model=GenResponse[List[Union[ActorSimpleOut, ActorBase]]],
    response_model_exclude_none=True,
    summary="Retrieve all actors",
)
async def get_all_actors(
        details: bool = False, sw: ServiceWorker = Depends(get_sw)
) -> GenResponse[List[Union[ActorSimpleOut, ActorBase]]]:
    """
    Retrieve all actors. Choice between 2 response types. With details or not (default: false).

    **Without details:**
      - registered_name
      - public_name

    **Details include:**
       - global_role
       - description
       - editor_config
       - deactivated
    """
    model_class = ActorSimpleOut if details else ActorBase
    # todo: move query to sw, and make this the GET /actor route
    return sw.data_response(sw.actor.to_model(sw.actor.get_all(), model_class))


@router.get(
    "/get_all_paginated",
    response_model=GenResponse[List[Union[ActorSimpleOut, ActorBase]]],
    description="get all actors but paginate by their id",
)
async def get_all_actors(
        after_id: int = Query(0, gt=0),
        limit: int = Query(50, gt=0),
        details: bool = False,
        sw: ServiceWorker = Depends(get_sw),
) -> GenResponse[List[ActorBase]]:
    """
    Retrieve all actors. Choice between 2 response types. With details or not (default: false).

    **Without details:**
      - registered_name
      - public_name

    **Details include:**
       - global_role
       - description
       - editor_config
       - deactivated
    """
    model_class = ActorSimpleOut if details else ActorBase
    # todo: move query to sw, and make this the GET /actor route
    return sw.data_response(
        sw.actor.to_model(sw.actor.get_paginated_actors(after_id, limit), model_class)
    )


@router.get("/verify_email_address")
async def verify_email_address(
        registered_name: str,
        verification_code: str,
        sw: ServiceWorker = Depends(get_sw),
        current_actor: RegisteredActor = Depends(get_current_actor),
) -> simple_message_response:
    actor: RegisteredActor = sw.actor.crud_read(registered_name)
    # test the function!
    # 1. already logged in? should return just when not visitor
    if current_actor and actor != current_actor:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST,
            sw.messages.t("actor.wrong_username"),
            data={"registered_name": registered_name},
        )

    if actor.email_validated:
        return sw.msg_response("actor.already_verified")

    if EMAIL_VERIFICATION_CODE not in actor.configs:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST, sw.messages.t("actor.verification_expired")
        )

    verified = verify_hash(verification_code, actor.configs[EMAIL_VERIFICATION_CODE])

    if not verified:
        # return ErrorResponse(sw.messages.t("actor.verification_failed"))
        raise ApplicationException(
            HTTP_400_BAD_REQUEST,
            sw.messages.t("actor.verification_wrong"),
            {"verification_code": verification_code},
        )
    else:  # success
        sw.actor.edit_configs(actor, remove=[EMAIL_VERIFICATION_CODE])
        actor.email_validated = True
        sw.db_session.commit()
        return sw.msg_response("actor.verified")


@router.get("/resend_email_verification_mail", response_model=simple_message_response)
@limiter.limit(rate_limits.Actor.resend_email_verification_mail)
async def resend_email_verification_mail(
        registered_name: str, request: Request, sw: ServiceWorker = Depends(get_sw)
):
    print("resend...")
    db_actor: RegisteredActor = sw.actor.crud_read(registered_name)
    if db_actor.email_validated:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST, sw.messages.t("actor.already_verified")
        )
    email_sent = sw.actor.make_send_actor_verification_code(db_actor)
    if email_sent:
        return sw.msg_response("actor.email_sent")
    else:
        return sw.msg_response("actor.email_not_sent")


@router.get(
    "/init_password_reset",
    description="Find an actor by their email or username and send a password reset email",
)
@limiter.limit(rate_limits.Actor.init_password_reset)
async def init_password_reset(
        email_or_username: str, request: Request, sw: ServiceWorker = Depends(get_sw)
) -> GenResponse[Dict]:
    actor = sw.actor.find_by_email_or_username(email_or_username)
    if not actor:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST,
            msg=sw.messages.t("actor.account_not_found"),
        )
    else:
        reset_code = sw.actor.set_password_reset_code(actor)
        if True or env_settings().EMAIL_ENABLED:
            send_password_reset_email(
                email_to=actor.email,
                username=actor.registered_name,
                reset_code=reset_code,
            )
            return sw.msg_data_response(
                msg="actor.email_sent",
                data={"address": obscure_email_address(actor.email)},
            )
        else:
            reset_code_url = urljoin(
                env_settings().HOST,
                "basic/password_reset"
                + f"?user={actor.registered_name}&code={reset_code}",
            )
            logger.warning(
                f"email reset for user:{actor.registered_name}: {reset_code_url}"
            )
            raise ApplicationException(
                HTTP_503_SERVICE_UNAVAILABLE, sw.messages.t("actor.email_deactivated")
            )


@router.post("/reset_password")
def reset_password(
        password_reset: ActorPasswordResetIn, sw: ServiceWorker = Depends(get_sw)
) -> simple_message_response:
    actor: RegisteredActor = sw.actor.crud_read(password_reset.registered_name)

    if PASSWORD_RESET_CODE not in actor.configs:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST, sw.messages.t("actor.code_expired")
        )

    if not verify_hash(password_reset.code, actor.configs[PASSWORD_RESET_CODE]):
        raise ApplicationException(
            HTTP_400_BAD_REQUEST, sw.messages.t("actor.wrong_code")
        )

    sw.actor.reset_password(actor, password_reset.password)

    return sw.msg_response("actor.password_reset")


@router.get("/check_admin")
def check_admin(_=Depends(is_admin)):
    return 200
