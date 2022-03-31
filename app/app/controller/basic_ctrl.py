from logging import getLogger
from typing import Optional, List, Set

from deprecated.classic import deprecated
from fastapi import APIRouter, Body, Depends, WebSocket, Query
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import (
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED,
)

from app.dependencies import get_current_actor, get_sw
from app.globals import registered_plugins
from app.models.orm import RegisteredActor
from app.models.schema import EntrySearchQueryIn, SearchValueDefinition
from app.models.schema.actor import ActorOut
from app.models.schema.domain_models import DomainOut
from app.models.schema.entry_schemas import EntryOut
from app.models.schema.response import GenResponse, create_error_response
from app.services.entry import entries_query_builder
from app.services.service_worker import ServiceWorker
from app.services.websocket_handler import add_actor, get_ws_connection, remove_actor
from app.settings import env_settings, BACKEND_MESSAGE_COMPONENT
from app.util.common import guarantee_set
from app.util.consts import (
    CODE,
    TEMPLATE,
    LANGUAGE,
    DOMAIN,
    STATUS,
    PUBLISHED,
)
from app.util.exceptions import ApplicationException

router = APIRouter(prefix="/basic", tags=["Basic"])

logger = getLogger(__name__)


@router.get("/")
async def get():
    return {"status": "ok"}


@router.get("/init_data")
async def init_data(
        language: str = Query(env_settings().DEFAULT_LANGUAGE),
        sw: ServiceWorker = Depends(get_sw),
):
    logger.debug(f"init with {language}")

    languages = sw.messages.get_added_languages()
    active = sw.app.state.language_active_statuses
    # TODO just added the False default to prevent some crash on int. is that correct??....
    languages = list(filter(lambda lang: active.get(lang, False), languages))

    # should deliver multiple languages, as fallbacks and a basic set (no_domaim codes)
    platform = {
        "title": env_settings().PLATFORM_TITLE,
        "only_one_domain": sw.request.app.state.only_one_domain,
        "login_required": env_settings().LOGIN_REQUIRED
    }
    oauth_services = sw.oauth.get_services()

    map_access_token = None
    if env_settings().MAP_ACCESS_TOKEN:
        map_access_token = env_settings().MAP_ACCESS_TOKEN.get_secret_value()

    response = {
        "languages": list(languages),
        "platform": platform,
        "oauth_services": oauth_services,
        "user_guide_url": sw.translation.get_user_guide_link(language),
        "map_default_map_style": env_settings().MAP_DEFAULT_MAP_STYLE,
        # TODO should not be shared when login is required and user is not logged in
        "map_access_token": map_access_token,
    }

    if language != env_settings().DEFAULT_LANGUAGE:
        msgs: Optional[dict] = sw.messages.get_component("fe", [language])
        if msgs:
            response["messages"] = sw.messages.structure_messages([language], msgs)
        else:
            response["language"] = env_settings().DEFAULT_LANGUAGE

    return response


@router.get("/domain_basics")
async def domain_basics(
        domains: Optional[List[str]] = Query([]),
        language: str = Query(env_settings().DEFAULT_LANGUAGE),
        sw: ServiceWorker = Depends(get_sw),
        current_actor: RegisteredActor = Depends(get_current_actor),
):
    logger.debug(f"init with {domains}, {language}")

    if not current_actor and env_settings().LOGIN_REQUIRED:
        return create_error_response(HTTP_401_UNAUTHORIZED, "EN:Login required")

    domains_map = (
        {}
    )  # {d.name: d for d in sw.domain.get_all_domains_overview(language, fallback_language=True)}
    dmeta_dlangs = sw.domain.crud_read_dmetas_dlangs(
        guarantee_set(language), guarantee_set(domains)
    )
    dmeta_dlangs = sw.domain.filter_fallbacks(dmeta_dlangs, language)
    for d in [sw.domain.domain_data(dmeta_dlang) for dmeta_dlang in dmeta_dlangs]:
        domains_map[d.name] = d

    domains_out: List[DomainOut] = sorted(
        domains_map.values(), key=lambda x: getattr(x, "index")
    )
    # should deliver multiple languages, as fallbacks and a basic set (no_domain codes)
    include_slugs: Set[str] = set()
    for dmeta_dlang in dmeta_dlangs:
        include_slugs.update(
            dmeta_dlang.meta.content.get("include_entries", [])
        )  # older versions might not have that key
    required_languages = list({language, env_settings().DEFAULT_LANGUAGE})
    logger.debug(
        f"Init entry-search query: required[language:{required_languages}]; include[domains:{domains},slugs:{include_slugs}]"
    )
    include = [SearchValueDefinition(name=DOMAIN, value=domains)]
    if include_slugs:
        include.append(SearchValueDefinition(name=TEMPLATE, value=list(include_slugs)))
    entries = entries_query_builder(
        sw,
        current_actor,
        entrytypes={TEMPLATE, CODE},
        search_query=EntrySearchQueryIn(
            required=[
                SearchValueDefinition(name=LANGUAGE, value=required_languages),
                SearchValueDefinition(name=STATUS, value=[PUBLISHED]),
            ],
            include=include,
        ),
        join_objects=set(),
    ).all()  # options(defer('*'), undefer(Entry.id)).all()  # nice speedup... doesnt work with the new sqlalchemy
    logger.debug([(e.slug, e.type, e.domain) for e in entries])
    entries_out = []
    for e in entries:
        try:
            logger.debug(f"converting {e.slug}")
            entries_out.append(sw.entry.to_model(e, EntryOut))
        except ValidationError as err:
            logger.error(f"Not adding entry: {e.slug}/{e.language}")
            logger.error(err)

    response = {
        "domains": domains_out,
        "only_one_domain": sw.request.app.state.only_one_domain,
        "templates_and_codes": entries_out,
        "language": language,
    }

    if language != env_settings().DEFAULT_LANGUAGE:
        msgs: Optional[dict] = sw.messages.get_component("fe", [language])
        if msgs:
            response["messages"] = sw.messages.structure_messages([language], msgs)
        else:
            response["language"] = env_settings().DEFAULT_LANGUAGE

    return {"data": response}


# todo simply change it in the fe page: oauth_complete
@router.get("/oauth_complete", deprecated=True)
async def oauth_complete_depr(request: Request, sw: ServiceWorker = Depends(get_sw)):
    logger.warning(
        f"service {request.session.get('oauth_service')} uses deprecated endpoint"
    )
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


# TODO, this is just some testing and should work. however somehow when the client sends a disconnect a refreshes the
#  page


html = """
<!DOCTYPE html>
<html>
	<head>
		<title>Chat</title>
	</head>
	<body>
		<h1>WebSocket Chat</h1>
		<form action="" onsubmit="sendMessage(event)">
			<input type="text" id="messageText" autocomplete="off"/>
			<button>Send</button>
		</form>
		<ul id='messages'>
		</ul>
		<script>
			var ws = new WebSocket("ws://localhost:8100/api/base/ws");
			ws.onmessage = function(event) {
				var messages = document.getElementById('messages')
				var message = document.createElement('li')
				var content = document.createTextNode(event.data)
				message.appendChild(content)
				messages.appendChild(message)
			};
			function sendMessage(event) {
				var input = document.getElementById("messageText")
				if(input.value==='close') {
				  ws.close(1001)
				} else {
					ws.send(input.value)
					input.value = ''
					event.preventDefault()
				}
			}
		</script>
	</body>
</html>
"""


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # noinspection PyArgumentList
    add_actor(RegisteredActor(registered_name="test"), websocket)
    while True:
        data = await websocket.receive()
        if data["type"] == "websocket.receive":
            print(data["text"])
        elif data["type"] == "websocket.disconnect":
            # noinspection PyArgumentList
            remove_actor(RegisteredActor(registered_name="test"))
            return


@router.get("/user_guide")
async def user_guide(language: str, name: str, sw: ServiceWorker = Depends(get_sw)):
    return sw.messages.t(f"user_guide.{name}", language, BACKEND_MESSAGE_COMPONENT)


@router.get("/test_ws")
async def websocket_endpoint2():
    # noinspection PyArgumentList
    websocket = get_ws_connection(RegisteredActor(registered_name="test"))

    if websocket:
        await websocket.send_text(f"hi test")
        return 200
    else:
        return 404


@deprecated
@router.post(
    "/plugin",
    deprecated=True,
    description="Use plugin-controller router /plugin/{plugin_name}",
)
async def plugin_call(
        plugin_name: str,
        response: Response,
        data: dict = Body(None),
        sw: ServiceWorker = Depends(get_sw),
):
    if plugin_name in registered_plugins:
        try:
            result = registered_plugins[plugin_name](data)
            return result
        except ApplicationException as app_exc:
            raise app_exc
        except Exception as err:
            logger.exception(err)
            raise ApplicationException(
                HTTP_500_INTERNAL_SERVER_ERROR, "plugin execution failed"
            )
    else:
        logger.warning(f"unknown plugin requested: {plugin_name}")
        response.status_code = HTTP_422_UNPROCESSABLE_ENTITY
        return sw.error_response(HTTP_422_UNPROCESSABLE_ENTITY, "plugin does not exist")
