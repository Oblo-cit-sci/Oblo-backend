from logging import getLogger
from os import makedirs
from os.path import join, isdir
from random import randint
from typing import List, Optional, Dict, Any, Tuple, Union
from urllib.parse import urljoin

from passlib import pwd
from sqlalchemy import or_, and_, func, exists
from sqlalchemy.orm import undefer, Query
from sqlalchemy.orm.exc import NoResultFound
from starlette.requests import Request
from starlette.status import (
    HTTP_409_CONFLICT,
    HTTP_403_FORBIDDEN,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_400_BAD_REQUEST,
)

from app import settings
from app.models.orm import (
    RegisteredActor,
    Token,
    ActorEntryAssociation,
    Entry,
    DomainMeta,
    Actor,
    OAuthActor,
)
from app.models.schema import ActorSearchQuery, ActorBase
from app.models.schema.actor import (
    ActorPasswordUpdateIn,
    ActorEmailUpdateIn,
    ActorRegisterIn,
    ActorCredentialsIn,
    ActorUpdateIn,
    EditorConfig,
    ActorSimpleOut,
)
from app.services.code_entry import get_license_values
from app.services.entry import join_entrytype_filter, join_actor_filter
from app.services.service_worker import ServiceWorker
from app.settings import COMMON_DATA_FOLDER, env_settings
from app.util.consts import (
    REGISTERED_NAME,
    EMAIL,
    EMAIL_VERIFICATION_CODE,
    PROFILE_EDITED,
    PASSWORD_RESET_CODE,
    PUBLIC,
    PRIVATE,
    EDITOR_CONFIG,
    TO_DELETE_ENTRIES,
    DOMAIN,
    VISITOR,
    REGULAR,
)
from app.util.emails import send_new_account_email
from app.util.exceptions import ApplicationException
from app.util.files import read_orjson
from app.util.passwords import verify_hash, create_hash

logger = getLogger(__name__)


class ActorService:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    # noinspection PyDefaultArgument
    def crud_create(
        self,
        actor_model: ActorRegisterIn,
        configs: dict = {},
        global_role: str = None,
        email_validated: bool = None,
    ):
        # todo consider taking alternative settings.
        # todo remove password_confirm from the exclude list? default should be true
        # noinspection PyArgumentList
        actor = RegisteredActor(
            **actor_model.dict(
                exclude={"email_confirm", "password", "password_confirm", "settings"}
            ),
            public_name=actor_model.registered_name,
            hashed_password=create_hash(actor_model.password.get_secret_value()),
            configs={
                **configs,
                PROFILE_EDITED: False,
            },
            # todo should rather be a global setting (including setting the fixed_domain)
            settings={
                **read_orjson(join(COMMON_DATA_FOLDER, "user_settings_default.json")),
                **actor_model.settings,
            },  # respect this order. actor-settings overwrite default
        )
        if global_role:
            actor.global_role = global_role
        if email_validated:
            actor.email_validated = email_validated
        # edit_settings(actor, add=[obj_in.settings.items()])
        self.db_session.add(actor)
        self.db_session.commit()
        self.create_user_folder(actor)
        return actor

    def base_q(self) -> Query:
        return self.db_session.query(RegisteredActor)

    # todo if this approach raise -> one, else one_or_none works... use it in the other sw...
    # could also replace the exists function...
    def crud_read(
        self, registered_name: str, raise_error: bool = True
    ) -> RegisteredActor:
        try:
            query = self.db_session.query(RegisteredActor).filter(
                RegisteredActor.registered_name == registered_name
            )
            if raise_error:
                return query.one()
            else:
                return query.one_or_none()
        except NoResultFound as err:
            if raise_error:
                logger.error(f"No user found: {registered_name}")
                raise err

    def exists(self, registered_name: str) -> bool:
        return self.db_session.query(
            exists().where(RegisteredActor.registered_name == registered_name)
        ).scalar()

    def crud_update(self, current_actor: RegisteredActor, obj_in: ActorUpdateIn):
        for (k, v) in obj_in.dict(exclude_none=True).items():
            if k == "settings":
                self.edit_settings(current_actor, new_settings=v)
            elif k == "domain":
                # domain specific profile answers
                self.edit_configs(current_actor, add={k: v})
            else:
                # print("actor profile", k, v)
                setattr(current_actor, k, v)
        self.edit_configs(current_actor, add={PROFILE_EDITED: True})
        self.db_session.add(current_actor)
        self.db_session.commit()

    def get_all(self, include_deactivated: bool = False) -> List[RegisteredActor]:
        """
        retrieve all actors
        :param include_deactivated: filter out deactivated actors
        :return: list of actors
        """
        return (
            self.base_q()
            .filter(
                RegisteredActor.registered_name != VISITOR,
                RegisteredActor.account_deactivated == include_deactivated,
            )
            .all()
        )

    def to_model(
        self,
        actors: Union[List[RegisteredActor], RegisteredActor],
        model: Union[ActorSimpleOut, ActorBase],
    ) -> Union[List[ActorSimpleOut], List[ActorBase], ActorSimpleOut, ActorBase]:
        """
        convert a list of actors/ or a singular actor to a list of actor-models
        :param actors:
        :param model:
        :return:
        """
        if isinstance(actors, list):
            return [model.from_orm(actor) for actor in actors]
        else:
            return model.from_orm(actors)

    def create_user_folder(self, actor: RegisteredActor, exist_ok: bool = True) -> bool:
        user_folder = join(settings.USER_DATA_FOLDER, actor.registered_name)
        if isdir(user_folder) and not exist_ok:
            logger.warning(f"actor folder already exists for {actor.registered_name}")
            return False
        else:
            makedirs(user_folder, exist_ok=exist_ok)
            return True

    def get_actor_path(self, registered_name: str):
        return join(settings.USER_DATA_FOLDER, registered_name)

    def username_or_email_exists(
        self, username: str, email: str, raise_error: bool
    ) -> bool:
        users = (
            self.db_session.query(RegisteredActor)
            .filter(
                or_(
                    RegisteredActor.registered_name == username,
                    RegisteredActor.email == email,
                )
            )
            .all()
        )
        if len(users) == 0:
            return False
        else:
            args = {REGISTERED_NAME: username, EMAIL: email}
            exists: List[str] = []
            for u in users:
                exists.extend(
                    field for field in args.keys() if getattr(u, field) == args[field]
                )
            msg = ""
            if REGISTERED_NAME in exists:
                msg += self.root_sw.messages.t("actor.s.name_taken") + ". "
            if EMAIL in exists:
                msg += self.root_sw.messages.t("actor.s.email_taken")
            if raise_error:
                raise ApplicationException(HTTP_409_CONFLICT, msg=msg, data=args)
            else:
                return True

    def find_by_email_or_username(
        self, email: str, username: str = None
    ) -> Optional[RegisteredActor]:
        email = email.lower()
        if not username:
            username = email
        username = username.lower()
        q = self.db_session.query(RegisteredActor)

        return (
            q.filter(
                or_(
                    RegisteredActor.registered_name == username,
                    RegisteredActor.email == email,
                )
            )
            .options(undefer(RegisteredActor.hashed_password))
            .one_or_none()
        )

    def login(self, actor: Actor, password: str, request: Request):
        credentials = ActorCredentialsIn(
            registered_name=actor.registered_name, password=password
        )
        self.verify_credentials(credentials)
        request.session["user"] = actor.registered_name

    def token_login(
        self, user_agent: str, actor_credentials: ActorCredentialsIn, request: Request
    ) -> Tuple[RegisteredActor, Token]:

        db_actor: RegisteredActor = self.verify_credentials(actor_credentials)
        token = self.create_auth_token(db_actor, "bearer")
        # do that anyway...
        request.session["user"] = actor_credentials.registered_name
        self.db_session.commit()
        return db_actor, token

    def oauth_login(self, actor: Union[RegisteredActor, OAuthActor], request: Request):
        if isinstance(actor, RegisteredActor):
            request.session["user"] = actor.registered_name
        else:
            ApplicationException(501)

    def verify_credentials(self, credentials: ActorCredentialsIn) -> RegisteredActor:
        db_actor: RegisteredActor = self.crud_read(credentials.registered_name)
        # oauth users pass this...
        if self.is_oauth_user(db_actor):
            verified = True
        else:
            verified = verify_hash(credentials.password.get_secret_value(), db_actor.hashed_password)
        if not verified:
            raise ApplicationException(
                status_code=HTTP_403_FORBIDDEN, msg="Incorrect username or password"
            )
        return db_actor

    def search(self, config: ActorSearchQuery):
        query = self.db_session.query(RegisteredActor)
        if config.name:
            # noinspection PyUnresolvedReferences
            query = query.filter(
                or_(
                    RegisteredActor.registered_name.ilike(config.name + "%"),
                    RegisteredActor.public_name.ilike("%" + config.name + "%"),
                )
            ).filter(RegisteredActor.registered_name != "visitor")
        return query.all()

    def create_auth_token(self, actor: RegisteredActor, token_type: str) -> Token:
        all_token = list(actor.token)
        for token in all_token:
            if token.token_type == token_type:
                logger.debug("updating token")
                token.update()
                return token
        token = Token(actor)
        self.db_session.add(token)
        return token

    def set_password_reset_code(self, actor: RegisteredActor) -> str:
        reset_code = pwd.genword(length=32)
        hashed_code = create_hash(reset_code)
        self.edit_configs(actor, add={PASSWORD_RESET_CODE: hashed_code})
        self.db_session.commit()
        return reset_code

    def get_all_users_public_entries(self) -> Dict[str, int]:
        """
        @return: a dict registered_name: number of public regular entries
        """
        return dict(
            self.db_session.query(RegisteredActor.registered_name, func.count(Entry.id))
            .group_by(RegisteredActor.registered_name)
            .filter(
                and_(
                    ActorEntryAssociation.entry_id == Entry.id,
                    ActorEntryAssociation.actor_id == RegisteredActor.id,
                    ActorEntryAssociation.role == "creator",
                )
            )
            .filter(Entry.type == REGULAR)
            .filter(Entry.public)
            .all()
        )

    def validate_settings(self, settings_data: Dict):
        for (k, v) in settings_data.items():
            # in the end, thats a config
            if k == "default_license":
                if v not in get_license_values(self.root_sw):
                    raise ApplicationException(
                        HTTP_400_BAD_REQUEST, msg="invalid license"
                    )
            elif k == "default_privacy":
                if v not in [PUBLIC, PRIVATE]:
                    raise ApplicationException(
                        HTTP_400_BAD_REQUEST, msg="invalid privacy"
                    )
            elif k == "ui_language":
                if (
                    v not in self.root_sw.messages.get_added_languages()
                ):  # todo, somewhere else obv.
                    raise ApplicationException(
                        HTTP_400_BAD_REQUEST, msg="invalid ui language"
                    )
            elif k == "fixed_domain":
                domain_names = [
                    dn[0] for dn in self.db_session.query(DomainMeta.name).all()
                ] + [None]
                if v not in domain_names:
                    raise ApplicationException(
                        HTTP_400_BAD_REQUEST, msg="invalid fixed domain"
                    )

    def make_send_actor_verification_code(
        self, actor: RegisteredActor
    ) -> Tuple[bool, Optional[str]]:
        verification_code = pwd.genword(length=32)
        # todo just do
        #  actor.configs[EMAIL_VERIFICATION_CODE] = create_hash(verification_code)
        #  flag_modified(actor, "configs")
        self.edit_configs(
            actor, add={EMAIL_VERIFICATION_CODE: create_hash(verification_code)}
        )
        self.db_session.commit()
        if env_settings().EMAIL_ENABLED:
            send_new_account_email(
                email_to=actor.email,
                username=actor.registered_name,
                verification_code=verification_code,
            )
            return True, verification_code
        else:
            username = actor.registered_name
            logger.warning(
                "Verification url:%s ",
                urljoin(
                    env_settings().HOST,
                    "basic/verify_email_address?"
                    + f"user={username}&code={verification_code}",
                ),
            )
            return False, verification_code

    def change_password(
        self, current_actor: RegisteredActor, obj_in: ActorPasswordUpdateIn
    ):
        verified = verify_hash(
            obj_in.actual_password.get_secret_value(), current_actor.hashed_password
        )
        if not verified:
            raise ApplicationException(
                status_code=HTTP_403_FORBIDDEN, msg="Incorrect password"
            )

        current_actor.hashed_password = create_hash(obj_in.password.get_secret_value())
        self.db_session.commit()

    def change_email(self, current_actor, obj_in: ActorEmailUpdateIn):
        verified = verify_hash(
            obj_in.password.get_secret_value(), current_actor.hashed_password
        )
        self.email_exists(obj_in.email)
        if not verified:
            raise ApplicationException(
                status_code=HTTP_403_FORBIDDEN, msg="Incorrect password"
            )
        current_actor.email = obj_in.email
        self.db_session.commit()

    def email_exists(self, email, throw_error: bool = True) -> bool:
        user = (
            self.db_session.query(RegisteredActor)
            .filter(RegisteredActor.email == email)
            .first()
        )
        if user:
            if throw_error:
                raise ApplicationException(
                    HTTP_409_CONFLICT, msg="Email already taken", data={"email": email}
                )
            return True
        return False

    # noinspection PyDefaultArgument
    def edit_jsonb_column(
        self,
        actor: RegisteredActor,
        column_name,
        *,
        add: Dict[str, Any] = {},
        remove: List[str] = (),
    ) -> Dict[str, Any]:
        """
        @todo  this approach (copying and replacing the whole dict was implemented cuz I didnt know of flag_modified
        However this abstraction is maybe ok to have
        @param actor:
        @param column_name:
        @param add:
        @param remove:
        @return:
        """
        data = getattr(actor, column_name)
        if data is None:
            raise ApplicationException(
                HTTP_500_INTERNAL_SERVER_ERROR,
                f"wrong db access, actor has no column {column_name}",
            )
        new_data = {**data}
        # print(f"existing data {column_name}", new_data)
        for (k, v) in add.items():
            new_data[k] = v
        for k in remove:
            del new_data[k]
        # print("resulting data", new_data)
        setattr(actor, column_name, new_data)
        return new_data

    def reset_password(self, actor: RegisteredActor, password):
        actor.hashed_password = create_hash(password)
        self.edit_configs(actor, remove=[PASSWORD_RESET_CODE])
        self.db_session.commit()

    # noinspection PyDefaultArgument
    def edit_configs(
        self,
        actor: RegisteredActor,
        *,
        add: Dict[str, Any] = {},
        remove: List[str] = (),
    ):
        self.edit_jsonb_column(actor, "configs", add=add, remove=remove)

    # noinspection PyDefaultArgument
    def edit_settings(self, actor: RegisteredActor, new_settings: Dict[str, Any] = {}):
        self.validate_settings(new_settings)
        self.edit_jsonb_column(actor, "settings", add=new_settings)

    def add_config_share(self, actor: RegisteredActor) -> dict:
        # todo should be separated cleaner.
        # maybe, in the config a share key
        cs = {}
        configs = actor.configs
        cs[PROFILE_EDITED] = configs.get(PROFILE_EDITED, False)
        if configs.get(EDITOR_CONFIG):
            cs[EDITOR_CONFIG] = configs[EDITOR_CONFIG]
        if configs.get(DOMAIN):
            cs[DOMAIN] = configs[DOMAIN]
        return cs

    def logout(self, current_actor: RegisteredActor, request: Request) -> bool:
        if auth_header := request.headers.get("Authorization"):
            token_type, access_token = auth_header.split(" ")
            token: Token = (
                self.db_session.query(Token)
                .filter(
                    Token.actor == current_actor,
                    Token.token_type == token_type.lower(),
                    Token.access_token == access_token,
                )
                .one_or_none()
            )
            if token:
                self.db_session.delete(token)
                self.db_session.commit()
        if request.session.get("user"):
            del request.session["user"]
        return False

    def get_delete_init_entries(self, current_actor: RegisteredActor):
        """
        A list of entries that can be deleted if a user deletes their account:
        - all their private posts, where no other actor has a role
        -
        """
        q = self.db_session.query(Entry)
        q = join_entrytype_filter(q)
        q = join_actor_filter(q, current_actor)
        q = q.filter(Entry.private)
        entries: List[Entry] = q.all()
        # logger.warning(entries)
        # todo could also be a filter...
        to_delete = []
        for e in entries:
            logger.debug(f"check entry for delete: only one user? :{len(e.actors)== 1}")
            if len(e.actors) == 1:
                to_delete.append(e)
        self.edit_configs(
            current_actor, add={TO_DELETE_ENTRIES: [str(e.uuid) for e in to_delete]}
        )
        self.db_session.commit()
        return to_delete

    # todo give the option to not delete all entries
    # noinspection PyDefaultArgument
    def delete(
        self,
        current_actor: RegisteredActor,
        save_entries: List[str] = [],
    ):
        to_delete = current_actor.configs[TO_DELETE_ENTRIES]
        for save_e in save_entries:
            to_delete.remove(save_e)

        to_delete_ids = (
            self.db_session.query(Entry).filter(Entry.uuid.in_(to_delete)).all()
        )
        for e in to_delete_ids:
            self.db_session.delete(e)
        self.edit_configs(current_actor, remove=[TO_DELETE_ENTRIES])

        current_actor.email = None
        current_actor.hashed_password = None
        current_actor.location = None
        current_actor.account_deactivated = True
        # todo temporary solution to avoid collision of other users
        current_actor.registered_name = (
            "DEL_" + current_actor.registered_name + "_" + str(randint(1000, 9999))
        )
        self.db_session.commit()

    def get_config(
        self, of_actor: RegisteredActor, config_name: str
    ) -> Union[EditorConfig]:
        configs = of_actor.configs
        if config_name == EDITOR_CONFIG:
            editor_config = EditorConfig.parse_obj(configs[EDITOR_CONFIG])
            editor_config.global_role = of_actor.global_role
            return editor_config
        else:
            raise ApplicationException(400, f"No config of name: {config_name}")

    def get_visitor(self) -> RegisteredActor:
        return self.crud_read(VISITOR)

    def get_oauth_data(self, actor: RegisteredActor, service_name: str) -> Dict:
        return actor.configs.get("oauth", {}).get(service_name, {})

    def is_oauth_user(self, actor: RegisteredActor) -> bool:
        return actor.registered_name.startswith("oauth_")
