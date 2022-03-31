from logging import getLogger

from fastapi import APIRouter, Depends
from starlette.datastructures import URL
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.status import HTTP_400_BAD_REQUEST

from app.models.schema.actor import ActorOut
from app.models.schema.response import GenResponse
from app.services.service_worker import ServiceWorker
from app.dependencies import get_sw
from app.util.exceptions import ApplicationException

router = APIRouter(prefix="/oauth", tags=["OAuth"])

logger = getLogger(__name__)


@router.get("/oauth_services")
async def get_oauth_services(sw: ServiceWorker = Depends(get_sw)):
    return sw.oauth.get_services()


@router.get("/init_oauth")
async def init_oauth(
    request: Request, service: str, sw: ServiceWorker = Depends(get_sw)
):
    try:
        redirect_response: RedirectResponse = await sw.oauth.init_oauth(
            request, service
        )
    except Exception as err:
        logger.exception(err)
        return RedirectResponse(
            URL(request.headers.get("referer")).include_query_params(error="true")
        )
    if not redirect_response:
        raise ApplicationException(HTTP_400_BAD_REQUEST, "unknown service")
    return redirect_response


@router.get("/oauth_complete")
async def oauth_complete(request: Request, sw: ServiceWorker = Depends(get_sw)):
    actor, is_new_actor = await sw.oauth.complete_flow(request)
    if not actor:
        raise ApplicationException(
            HTTP_400_BAD_REQUEST,
            msg=sw.messages.t("actor.account_not_found"),
        )
    else:
        sw.actor.oauth_login(actor, request)
        actor_out: ActorOut = ActorOut.from_orm(actor)
        actor_out.config_share = sw.actor.add_config_share(actor)
        return GenResponse(
            data={"actor": actor_out, "is_new_actor": is_new_actor},
            msg=sw.messages.t("actor.login_ok", actor.settings["ui_language"]),
        )


@router.post("/oauth_register")
async def oauth_register(
    # request: Request,
    actor_data: ActorOut,
    sw: ServiceWorker = Depends(get_sw),
):
    actor = sw.actor.crud_read(actor_data.registered_name)
    await sw.oauth.oauth_reg_user_activate(actor, actor_data)
    return sw.msg_response("actor.login_ok")
