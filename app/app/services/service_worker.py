from logging import getLogger
from typing import Optional, Type, Any, Dict

from deprecated.classic import deprecated
from fastapi import HTTPException, FastAPI
from pydantic import BaseModel, Extra
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import JSONResponse

# from app.setup import Session
from app.models.orm import Entry, Base, RegisteredActor
from app.models.schema import EntryMainModel
from app.models.schema.response import (
    GenResponse,
    simple_message_response,
    create_error_response,
)
from app.settings import env_settings
from app.util.consts import PROD
from app.util.csv_transformer import transform_to_csv
from app.util.exceptions import ApplicationException

logger = getLogger(__name__)


# todo: do we need this?
# dont use reference to sw.state objects but rather pass them to the methods...
class ServiceWorkerState(BaseModel):
    """
    Service Worker State
    """

    current_entry: Optional[EntryMainModel]
    current_db_entry: Optional[Entry]
    actor: Optional[RegisteredActor]
    template_code_config_extra_stash: Optional[Dict[Type[BaseModel], Extra]] = {}

    class Config:
        arbitrary_types_allowed = True


class ServiceWorker:

    # noinspection PyDefaultArgument
    def __init__(
        self, db_session: Session = None, request: Request = None, options: dict = {},
            app: FastAPI = None
    ):
        self.db_session: Session = db_session
        self.request = request
        self.active_key: str = ""

        from app.services.entry_sw import EntryServiceWorker
        from app.services.init_data_sw import DataServiceWorker
        from app.services.tag_sw import TagService
        from app.services.translation_sw import TranslationService
        from app.services.actor_sw import ActorService
        from app.services.model_helper_sw import ModelHelperService
        from app.services.messages_sw import MessagesService
        from app.services.code_sw import CodeService
        from app.services.oauth_sw import OAuthService
        from app.services.template_code_entry_sw import TemplateCodeService

        self.actor = ActorService(self)
        # self.language = LanguageServiceWorker(self, request.headers.get("Accept-Language") if request else None,
        #                                       options)
        self.messages = MessagesService(
            self, request.headers.get("Accept-Language") if request else None, options
        )
        self.entry = EntryServiceWorker(self)
        self.data = DataServiceWorker(self)
        self.tag = TagService(self)
        self.translation = TranslationService(self)
        self.models = ModelHelperService(self)
        self.codes = CodeService(self)
        self.template_codes = TemplateCodeService(self)
        self.oauth = OAuthService(self)

        self.state: ServiceWorkerState = ServiceWorkerState()
        if request:
            self.app = request.app
        else:
            self.app = app
        if not self.app and env_settings().ENV == PROD:
            logger.warning("Serviceworker initialized without app")
    # would be nice to compare the performance of this compared to the rest
    @property
    def domain(self):
        from app.services.domain_sw import DomainServiceWorker

        return DomainServiceWorker(self)

    def transform2csv(self, entry: Entry):
        # better use crud
        template = entry.template
        if template:
            return transform_to_csv(entry, template)
        else:
            ApplicationException(500, "no template found")

    def msg_response(self, msg: str, language: Optional[str] = None) -> GenResponse:
        return simple_message_response(msg=self.messages.t(msg, language))

    def msg_data_response(self, msg: str, data: Any, language: Optional[str] = None):
        return GenResponse(data=data, msg=self.messages.t(msg, language))

    def data_response(self, data: Any):
        return GenResponse(data=data)

    def error_response(
        self, code: int, msg: str = "", data: dict = None
    ) -> JSONResponse:
        return create_error_response(code, msg=self.messages.t(msg), data=data)

    def t(self, msg):
        return self.messages.t(msg)

    # def validate_code_entry(self, entrybase_in: EntryInitBase, entry_lang_in: Optional[EntryInitLang] = None):
    #     if not entry_lang_in:
    #         if entrybase_in.template == "value_list":
    #             # entrybase_in = CodeEntry_ListBase(entrybase_in)
    #             entrybase_in.values.list = ItemListBase(__root__=entrybase_in.values["list"])
    #         elif entrybase_in.template == "value_tree":
    #             logger.warning("TODO TREE")
    #     else:
    #         if entrybase_in.template == "value_list":
    #             entry_lang_in.values["list"] = ItemListLang(__root__=entry_lang_in.values["list"])
    #         elif entrybase_in.template == "value_tree":
    #             logger.warning("TODO TREE")

    def db_session_add(self, model: Base):
        self.db_session.add(model)
        return model

    def raise_error(self, status_code, msg):
        raise HTTPException(status_code, detail=self.t(msg))


