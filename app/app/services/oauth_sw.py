import glob
from logging import getLogger
from os.path import join, basename
from typing import Optional, Union, Tuple
from urllib.parse import urljoin

import httpx
from authlib.integrations.starlette_client import OAuth
from pydantic import ValidationError
from sqlalchemy.orm.attributes import flag_modified
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY, HTTP_400_BAD_REQUEST

from app.models.orm import RegisteredActor
from app.models.orm.oauth_actor import OAuthActor
from app.models.schema.OAuthSchemas import ServiceConfig
from app.models.schema.actor import ActorOut
from app.services.service_worker import ServiceWorker
from app.settings import COMMON_DATA_FOLDER, env_settings, CONFIG_DIR
from app.util.consts import PROFILE_EDITED
from app.util.exceptions import ApplicationException
from app.util.files import read_orjson, JSONPath

logger = getLogger(__name__)


class OAuthHelper:
    def __init__(self):
        self.redirect_uri = urljoin(env_settings().HOST, "/oauth_complete")
        self.oauth = OAuth()
        self.services = []
        for file in glob.glob(join(CONFIG_DIR, "oauth_services/*.json")):
            data = JSONPath(file).read()
            try:
                validated_config = ServiceConfig.parse_obj(data)
                self.oauth.register(**data)
                self.services.append(
                    {
                        "service_name": validated_config.name,
                        "service_icon_url": str(validated_config.service_icon_url),
                    }
                )
            except ValidationError as err:
                logger.error(err)
                logger.error(f"Oauth service not registered, file: {basename(file)}")


def setup_oauth():
    global oauth_helper
    oauth_helper = OAuthHelper()


oauth_helper: OAuthHelper = None


if not oauth_helper:
    setup_oauth()


class OAuthService:
    def __init__(self, root_sw: ServiceWorker):
        global oauth_helper
        self.root_sw = root_sw
        self.db_session = root_sw.db_session
        self.helper: OAuthHelper = oauth_helper
        self.oauth = self.helper.oauth

    def get_services(self):
        return self.helper.services

    def service_names(self):
        return [s["service_name"] for s in self.helper.services]

    async def init_oauth(
        self, request: Request, service_name: str
    ) -> Optional[RedirectResponse]:
        if service_name not in self.service_names():
            raise ApplicationException(404, "unknown service")
        service = self.oauth.create_client(service_name)

        res: RedirectResponse = await service.authorize_redirect(
            request, self.helper.redirect_uri
        )
        request.session["oauth_service"] = service_name
        return res

    async def complete_flow(
        self, request: Request
    ) -> Tuple[Union[RegisteredActor, OAuthActor], bool]:
        """
        @param request:
        @return: Actor and bool, if actor is new or existed already
        """
        service_name = request.session.get("oauth_service")

        if not service_name:
            raise ApplicationException(HTTP_422_UNPROCESSABLE_ENTITY, "no service")

        service = self.oauth.create_client(service_name)

        logger.info(f"completing flow: {service_name}")
        try:
            token_response = await service.authorize_access_token(request)
            access_token = token_response["access_token"]
        except Exception as err:
            logger.error(err)
            raise ApplicationException(HTTP_400_BAD_REQUEST, "cannot obtain token")

        user_info = None
        try:
            user_info = self.fetch_user_info(service_name, access_token)
            # print(user_info)
            user_mapping = service.server_metadata["user_mapping"]
            oauth_user_data = {}
            for key, key_in_info in user_mapping.items():
                # can be multiple that are joined together (public name, orcid)
                if isinstance(key_in_info, str):
                    oauth_user_data[key] = user_info[key_in_info]
                elif isinstance(key_in_info, list):
                    oauth_user_data[key] = ", ".join(
                        user_info[k] for k in key_in_info
                    )  # print(oauth_user_data)
            # todo temp hack to get oauth users in. should be a separate table.
            # oauth_user: Optional[OAuthActor] = self.get_actor(service_name, oauth_user_data["username"])
            oauth_user_in_reg_actor: Optional[RegisteredActor] = self.get_reg_actor(
                service_name, oauth_user_data["username"]
            )
            # print("existing user", oauth_user_in_reg_actor)
            if oauth_user_in_reg_actor:
                # self.update_user(oauth_user, token_response, access_token, oauth_user_data)
                self.update_reg_actor(
                    oauth_user_in_reg_actor,
                    service_name,
                    token_response,
                    oauth_user_data,
                )
                logger.warning(f"updated actor {oauth_user_in_reg_actor}")
                # we use account_deactivated to check if the user agreed (user is deactivated until they agreed)
                return (
                    oauth_user_in_reg_actor,
                    oauth_user_in_reg_actor.account_deactivated,
                )
        except Exception as err:
            logger.error(f"received user_info {user_info}")
            logger.error(err)
            raise ApplicationException(HTTP_400_BAD_REQUEST, "cannot obtain userdata")

        # oauth_user: OAuthActor = self.create_oauth_user(service_name, token_response, access_token, oauth_user_data)
        oauth_user: RegisteredActor = self.create_oauth_reg_user(
            service_name, token_response, oauth_user_data
        )
        self.root_sw.actor.create_user_folder(oauth_user)
        logger.warning(f"created actor {oauth_user}")
        return oauth_user, True

    def fetch_user_info(self, service_name: str, access_token: str) -> dict:
        # logger.warning(f"{service_name}, {token_data}")
        service = self.oauth.create_client(service_name)
        # logger.warning(service.server_metadata)
        params = {}
        if service.server_metadata.get("access_token_as_query_param", False):
            params["access_token"] = access_token
        res = httpx.get(
            service.server_metadata["userinfo_endpoint"],
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        if res.status_code == 200:
            # logger.warning(res.json())
            return res.json()

    def get_actor(self, service: str, username: str) -> Optional[OAuthActor]:
        return (
            self.db_session.query(OAuthActor)
            .filter(OAuthActor.service == service, OAuthActor.username == username)
            .one_or_none()
        )

    def get_reg_actor(self, service: str, username: str) -> Optional[RegisteredActor]:
        return (
            self.db_session.query(RegisteredActor)
            .filter(RegisteredActor.registered_name == f"oauth_{service}_{username}")
            .one_or_none()
        )

    def create_oauth_user(
        self,
        service: str,
        access_token_response: dict,
        access_token: str,
        user_data: dict,
    ):
        """
        todo not used yet...
        @param service:
        @param access_token_response:
        @param access_token:
        @param user_data:
        @return:
        """
        # noinspection PyArgumentList
        actor = OAuthActor(
            username=user_data["username"],
            service=service,
            access_token_data=access_token_response,
            access_token=access_token,
            user_data=user_data,
        )
        self.db_session.add(actor)
        self.db_session.commit()
        return actor

    def create_oauth_reg_user(
        self, service: str, access_token_response: dict, user_data: dict
    ):
        # todo this small method should be abstracted away. add automatically
        # noinspection PyArgumentList
        actor = RegisteredActor(
            registered_name=f"oauth_{service}_{user_data['username']}",
            public_name=user_data["public_name"],
            description=user_data.get("description", ""),
            email="",
            email_validated=True,
            configs={
                service: {
                    "access_token_data": access_token_response,
                    "user_data": user_data,
                    PROFILE_EDITED: False,
                }
            },
            account_deactivated=True,
            settings={
                **read_orjson(join(COMMON_DATA_FOLDER, "user_settings_default.json"))
            },  # respect this order. actor-settings overwrite default
        )

        actor = self.root_sw.db_session_add(actor)
        self.db_session.commit()
        return actor

    async def oauth_reg_user_activate(self, user: RegisteredActor, user_data: ActorOut):
        user.public_name = user_data.public_name
        user.email = user_data.email
        user.description = user_data.description
        user.account_deactivated = False
        self.db_session.commit()

    def update_user(
        self,
        actor: OAuthActor,
        service_name: str,
        access_token_response: dict,
        acces_token: str,
        user_data: dict,
    ):
        """
        todo not used yet...
        @param actor:
        @param service_name:
        @param access_token_response:
        @param acces_token:
        @param user_data:
        @return:
        """
        actor.access_token_data = access_token_response
        actor.access_token = acces_token
        actor.user_data = user_data
        flag_modified(actor, "access_token_data")
        flag_modified(actor, "user_data")
        self.db_session.commit()

    def update_reg_actor(
        self,
        actor: RegisteredActor,
        service_name: str,
        access_token_response: dict,
        user_data: dict,
    ):
        actor.configs["oauth"] = {
            service_name: {
                "access_token_data": access_token_response,
                "user_data": user_data,
            }
        }
        flag_modified(actor, "configs")
        self.db_session.commit()

    def post_to_service(self, actor: RegisteredActor, service_name: str, endpoint: str):
        oauth_data: dict = self.root_sw.actor.get_oauth_data(actor, service_name)
        if not oauth_data:
            logger.error(f"No OAuth-data for user: {actor} on service: {service_name}")
        else:
            pass
            # self.oauth.create_client(service_name).config
