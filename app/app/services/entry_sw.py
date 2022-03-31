from datetime import datetime
from logging import getLogger
from typing import List, Optional, Type, Union, Dict, Literal
from uuid import uuid4

import orjson
from jsonpath import jsonpath
from pydantic import ValidationError, types
from pydantic.error_wrappers import ErrorWrapper
from sqlalchemy import exists
from sqlalchemy.orm import Query
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import NoResultFound
from starlette.status import (
    HTTP_404_NOT_FOUND,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_401_UNAUTHORIZED,
)

from app.globals import registered_plugins
from app.models.orm import Entry, RegisteredActor, Tag
from app.models.orm.relationships import EntryTagAssociation, ActorEntryAssociation
from app.models.schema import (
    EntryMeta,
    MapEntry,
    EntryActorRelationOut,
    ActorBase,
    EntryRef,
    AbstractEntry,
    EntryMainModel,
    EntryMainModelTypes,
)
from app.models.schema.aspect_models import AspectBaseIn
from app.models.schema.entry_schemas import (
    EntryOut,
    EntryRegular,
    EntryApiUpdateIn,
    EntryReviewIn,
    EntryLangUpdate,
    EntryAction,
)
from app.models.schema.template_code_entry_schema import (
    TemplateBaseInit,
    TemplateMerge,
    EntryEntryRef,
    CodeTemplateMinimalOut,
)
from app.services.entry import fix_location_aspect, update_entry_references
from app.services.service_worker import ServiceWorker
from app.services.util.aspect import aspect_default_value
from app.settings import env_settings
from app.util.common import replace_value
from app.util.consts import (
    CREATOR,
    CODE,
    PUBLIC,
    SELECT,
    MULTISELECT,
    TREE,
    LIST,
    COMPOSITE,
    COMPONENTS,
    TAG,
    REVIEWER,
    VISITOR,
    PUBLISHED,
    REQUIRES_REVIEW,
    REGULAR,
    ENTRY_TYPES_LITERAL,
    NO_DOMAIN,
    ACCESS_KEY_HASH,
    TITLE,
    ASPECTS,
    VALUES,
    DESCRIPTION,
    UUID,
    EDITOR,
    BASE_SCHEMA_ENTRIES,
    CONCRETE_ENTRIES, SLUG, TEMPLATE, TEMPLATE_VERSION, TYPE, LICENSE, PRIVACY, ENTRY_REFS, TAGS, STATUS, VERSION,
    LANGUAGE, DOMAIN,
)
from app.util.dict_rearrange import deep_merge, extract_diff
from app.util.exceptions import ApplicationException
from app.util.location import set_visible_location
from app.util.models import fix_constructed_entry_actors
from app.util.passwords import uuid_and_hash, verify_hash

logger = getLogger(__name__)

EntryModels = Union[EntryMeta, MapEntry, EntryOut]
EntryType = Type[EntryModels]

EntryInModels = Union[TemplateBaseInit, TemplateMerge]


class EntryServiceWorker:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    def crud_get(self, uuid: types.UUID, raise_error: bool = True) -> Optional[Entry]:
        """
        Get entry by uuid
        @param uuid: if error should be raised when the entry is not found.
        @param raise_error: if error should be raised when the entry is not found.
        """
        entry = self.base_q().filter(Entry.uuid == uuid).one_or_none()
        if not entry and raise_error:
            msg = f"entry not found"
            logger.error(msg)
            self.raise_not_found({"uuid": str(uuid)})
        return entry

    def exists(self, uuid: types.UUID):
        return self.db_session.query(exists().where(Entry.uuid == uuid)).scalar()

    def check_has_write_access(
            self, entry: Entry, actor: RegisteredActor, raise_error=True
    ) -> bool:
        # todo: later there must always be an actor... so at least visitor
        write_access: bool = entry.has_write_access(actor)
        if write_access:
            return True
        if request := self.root_sw.request:
            if str(entry.uuid) in request.session.get("created_entries", []):
                return True
        if raise_error:
            # todo go to exception-handler and and fill in translation of detail
            raise self.root_sw.raise_error(
                HTTP_401_UNAUTHORIZED, "api.error.not_authorized"
            )
        return False

    def base_q(self) -> Query:
        """
        Base query for entries.
        """
        return self.db_session.query(Entry)

    def raise_not_found(self, data):
        """
        Raise not found error
        """
        raise ApplicationException(HTTP_404_NOT_FOUND, f"Entry not found", data)

    def process_entry_post(
            self, entry_in: EntryRegular, current_actor: RegisteredActor
    ):
        """
        post processing after a regular entry is submitted/patched
        """
        # noinspection PyArgumentList
        db_entry = Entry(
            **entry_in.dict(
                exclude={"template", "actors", "tags", "entry_refs", "attached_files"}
            )
        )

        if entry_in.template:
            by_uuid = False
            if isinstance(entry_in.template, EntryRef):
                if entry_in.template.uuid:
                    by_uuid = True
            try:
                if by_uuid:
                    db_entry.template = self.crud_get(entry_in.template.uuid)
                else:
                    db_entry.template = self.root_sw.template_codes.resolve_reference(entry_in.template)
                    # logger.warning("entry with missing template uuid, will try template-slug for language/w backup")
                    # todo could later be: template.language, template.version
                    # db_entry.template = self.root_sw.template_codes.get_by_slug_lang(
                    #     entry_in.template.slug
                    # )
            except NoResultFound:
                # todo orjson mess
                raise ApplicationException(
                    HTTP_400_BAD_REQUEST,
                    "template with given uuid doesnt exist",
                    data=orjson.loads(orjson.dumps(entry_in.template.dict())),
                )
        # todo might already be done by the frontend, tho, this is more safe!
        self.update_entry_roles(db_entry, entry_in.actors, current_actor)

        db_entry.status = (
            REQUIRES_REVIEW
            if self.check_requires_review(db_entry, current_actor)
            else PUBLISHED
        )

        if not current_actor:
            self.set_as_visitor_entry(db_entry)

        self.update_entry_tags(db_entry, entry_in.tags)
        # for a in e_db_in["attached_files"]:
        # 	replace_value(a, ["file_uuid"], lambda uuid: str(uuid))

        self.db_session.add(db_entry)
        self.db_session.commit()

        logger.debug(f"Entry created: {db_entry.title}")
        return db_entry

    def update_entry_roles(
            self,
            entry: Entry,
            entry_roles_data: List[EntryActorRelationOut],
            new_creator_o_editor: RegisteredActor = None,
    ):
        actor_obj_map: dict[str, ActorEntryAssociation] = {
            aer.actor.registered_name: aer for aer in entry.actors
        }
        actor_in_map: dict[str, EntryActorRelationOut] = {
            aer.actor.registered_name: aer for aer in entry_roles_data
        }

        def create_with_role(
                actor: RegisteredActor, role_: str
        ) -> EntryActorRelationOut:
            return EntryActorRelationOut(actor=ActorBase.from_orm(actor), role=role_)

        # insert new actor into model:
        if new_creator_o_editor:
            # if its already in the entry, leave it
            if existing_role := actor_obj_map.get(new_creator_o_editor.registered_name):
                actor_in_map[new_creator_o_editor.registered_name] = create_with_role(
                    new_creator_o_editor, existing_role.role
                )
            else:
                # add it as creator or editor
                role = CREATOR if not actor_obj_map else EDITOR
                actor_in_map[new_creator_o_editor.registered_name] = create_with_role(
                    new_creator_o_editor, role
                )

        for (actor_name, new_role) in actor_in_map.items():
            # adding new actors to the entry
            if actor_name not in actor_obj_map:
                try:
                    db_actor = self.root_sw.actor.crud_read(actor_name)
                except NoResultFound:
                    logger.warning(f"Skipping actor. not found {actor_name}")
                    continue
                entry.actors.append(
                    ActorEntryAssociation(actor_id=db_actor.id, role=new_role.role)
                )
            else:
                # for those who are still there, check if the role changed
                if actor_obj_map[actor_name].role != new_role.role:
                    actor_obj_map[actor_name].role = new_role.role
        for (actor_name, removed_role) in actor_obj_map.items():
            if actor_name not in actor_in_map:
                entry.actors.remove(removed_role)

    def process_review(
            self,
            db_obj: Entry,
            entry_in: EntryApiUpdateIn,
            current_actor: RegisteredActor,
            new_status: Literal["published", "rejected"],
    ) -> Optional[Entry]:
        """
        process a review with a status
        """
        entry_in = EntryReviewIn.construct(**entry_in.dict(), status=new_status)
        # add current_actor as reviewer, but not if the cur actor added themself as creator

        if not list(
                filter(
                    lambda a: a["actor"]["registered_name"] == current_actor.registered_name
                              and a["role"] == CREATOR,
                    entry_in.actors,
                )
        ):
            entry_in.actors.append(
                EntryActorRelationOut(
                    actor=ActorBase.from_orm(current_actor), role=REVIEWER
                )
            )
        print("actors-pre", entry_in.actors)
        entry_in.actors = fix_constructed_entry_actors(entry_in.actors)
        # print("actors-post", entry_in.actors)
        # todo fileAttachments are probably still broken here, needs a similar fix as actors
        return self.update(db_obj=db_obj, entry_in=entry_in)

    def update(
            self,
            db_obj: Entry,
            entry_in: Union[EntryApiUpdateIn, EntryReviewIn],
    ) -> Optional[Entry]:

        update_dict = entry_in.dict(exclude_none=True)

        for (k, v) in update_dict.items():
            if k == "slug":
                if self.db_session.query(Entry).filter(Entry.slug == v).first():
                    raise ApplicationException(
                        HTTP_400_BAD_REQUEST, "slug already taken"
                    )
            elif k == "actors":
                self.update_entry_roles(db_obj, entry_in.actors)
            elif k == "tags":
                # TODO Tags dont update
                self.update_entry_tags(db_obj, entry_in.tags)
            elif k == "entry_refs":
                update_entry_references(self.db_session, db_obj, v)
            elif k == "template":
                # should be the same
                continue
            else:
                setattr(db_obj, k, v)

        for a in db_obj.attached_files:
            replace_value(a, ["file_uuid"], lambda uuid: str(uuid))

        db_obj.last_edit_ts = datetime.now()
        db_obj.version += 1
        self.db_session.commit()
        return db_obj

    # noinspection PyMethodMayBeStatic
    def create_entry_gen(
            self, db_obj: Entry, actor: RegisteredActor, result_type: EntryType
    ):
        """
        calls methods to privatize certain values (location, location-values) in the entry before sending it out.
        @param db_obj:
        @param actor:
        @param result_type:
        @return:
        """
        try:
            em = result_type.from_orm(db_obj)
            if result_type != MapEntry and db_obj.template:
                em.template = {"slug": db_obj.template.slug}

            set_visible_location(em, db_obj, actor)

            if result_type is EntryOut:
                fix_location_aspect(em, db_obj, actor)
            return em
        except ValidationError as err:
            logger.error(err)
            logger.warning(f"{db_obj.title} cannot be validated and will not be sent")

    def regular_out_add_protected_info(self, regular: EntryOut, db_obj: Entry, actor: RegisteredActor):
        self.add_has_entry_access_hash(regular, db_obj, actor)

    def create_entry_list(
            self, db_objs: List[Entry], actor: RegisteredActor, result_type: EntryType
    ) -> List[EntryModels]:
        """
        calls methods to privatize all entries. kicks out those which do not validate.
        calls create_entry_gen on all objects.
        @param db_objs:
        @param actor:
        @param result_type:
        @return:
        """
        result: List[EntryMeta] = []
        for db_obj in db_objs:
            em: EntryModels = self.create_entry_gen(db_obj, actor, result_type)
            if em:
                result.append(em)
        return result

    def get_aspect_references(
            self, aspect_data: AspectBaseIn, path: str = ""
    ) -> List[Dict]:
        if aspect_data.type in [SELECT, MULTISELECT, TREE] and isinstance(
                aspect_data.items, str
        ):
            reference = {
                "aspect_path": path + "." + aspect_data.name,
                "dest_slug": aspect_data.items,
            }
            if aspect_data.attr and aspect_data.attr.tag:
                reference["ref_type"] = TAG
                reference[TAG] = aspect_data.attr.tag
            else:
                reference["ref_type"] = CODE
            return [reference]
        elif aspect_data.type == LIST:
            return self.get_aspect_references(
                aspect_data.list_items, path + "." + aspect_data.name
            )
        elif aspect_data.type == COMPOSITE:
            references = []
            for component in getattr(aspect_data, COMPONENTS, []):
                refs = self.get_aspect_references(
                    component, path + "." + aspect_data.name
                )
                if refs:
                    references.extend(refs)
            return references
        return []

    def get_entry_references(self, base_model: TemplateBaseInit) -> List[EntryEntryRef]:
        """
        @param base_model:
        @return: Dict: aspect-loc, references slug
        """
        references = []
        for aspect in base_model.aspects:
            refs = self.get_aspect_references(aspect)
            references.extend(refs)
        return [EntryEntryRef.parse_obj(ref) for ref in references]

    def update_entry_tags(self, entry: Entry, entry_tags_data: Dict[str, List[str]]):
        """
        Creates EntryTagAssociation db objects
        @param entry:
        @param entry_tags_data: key: group-name (set in he template), value: list of tag-values
        """
        if entry_tags_data:
            tags_to_add: Dict[str, str] = {}
            for (new_tags_group_name, new_tags) in entry_tags_data.items():
                for new_tag in new_tags:
                    tags_to_add[new_tag] = new_tags_group_name

            db_tags_to_add = self.root_sw.tag.get_tags_from_entry_tags(
                entry, tags_to_add
            )
            new_tag_assoc = []
            for db_tag in db_tags_to_add:
                new_tag_assoc.append(
                    EntryTagAssociation(
                        tag=db_tag, group_name=tags_to_add[db_tag.value]
                    )
                )
            entry.tags = new_tag_assoc
        else:
            entry.tags = []

    # noinspection PyMethodMayBeStatic
    def check_requires_review(
            self, entry: Entry, current_actor: RegisteredActor
    ) -> bool:
        # logger.warning(f"entry review from new method "
        #                f"{entry_create_requires_review(self.root_sw, entry, current_actor)}")
        # TODO VISITOR?!
        if not current_actor or current_actor.global_role == VISITOR:
            return True
        if check_value_paths := entry.template.rules.get(
                "requires_review_if_missing", False
        ):
            for path in check_value_paths:
                result = jsonpath(entry.values, path)
                if result:  # its proper path.
                    value = result[0]
                    if not value:  # null, or empty list
                        return True
                else:
                    logger.warning(
                        "given path for requires_review_if_missing does not exist: {path}. Ignoring..."
                    )
        if current_actor.is_admin:
            return False
        # todo this little piece could be pulled into a function. since it might be user in other places.
        if current_actor.is_editor:
            if entry.domain in current_actor.configs["editor"]["domain"]:
                return False
        if entry.template.rules.get("requires_review", False):
            return True
        return False

    # noinspection PyMethodMayBeStatic
    def set_as_visitor_entry(self, entry: Entry):
        entry.privacy = PUBLIC
        entry.license = "CC0"

    def create_entry_tags(self, db_obj: Entry, tags_data):
        for tag_group, tags in tags_data.items():
            # this should include the referene entry, that holds the codes
            db_tags: List[Tag] = self.root_sw.tag.get_all(tags)
            tag_rels = [
                EntryTagAssociation(tag=tag, group_name=tag_group) for tag in db_tags
            ]
            db_obj.tags.extend(tag_rels)

    # noinspection PyMethodMayBeStatic
    def to_model(
            self,
            db_obj: Entry,
            model: Union[EntryMainModelTypes, Type[CodeTemplateMinimalOut]],
            attach_original: bool = False,
    ) -> Union[EntryMainModel, CodeTemplateMinimalOut]:  # todo nested Union?
        if model in [EntryOut, TemplateBaseInit, TemplateMerge]:
            # better use : entry_sw.create_entry_gen
            try:
                em = model.from_orm(db_obj)
            except Exception as e:
                logger.error(f"Failed to create entry model: {e}")
                raise e
            if attach_original:
                em._entry = db_obj
            if db_obj.template:
                # todo this is new! why do I need to do this?!
                em.template = EntryRef.from_orm(db_obj.template)
                em.template.version = db_obj.template_version
                try:
                    em.template.outdated = db_obj.template.version > em.template.version
                except Exception as err:
                    # todo lookup how pydantic throws ValidationErrors
                    raise ValidationError(
                        [ErrorWrapper(Exception(err), "")], AbstractEntry
                    )

            # if db_obj.entry_refs:
            #     em.entry_refs = [ref.reference for ref in db_obj.entry_refs]
            return em
        elif CodeTemplateMinimalOut:
            em = CodeTemplateMinimalOut.from_orm(db_obj)
            if db_obj.template:
                em.template.version = db_obj.template_version
                try:
                    em.template.outdated = db_obj.template.version > em.template.version
                except TypeError as err:
                    raise ValidationError([ErrorWrapper(err, "")], AbstractEntry)
            return em
        else:
            logger.warning("Unspecified model transformation. Only calling from_orm")
            return model.from_orm(db_obj)

    """
        FOR CREATING NEW REGULAR VALUES
    """

    # noinspection PyMethodMayBeStatic
    def template_default_values(self, template: Entry):
        values = {}
        aspects = template.aspects
        for aspect in aspects:
            values[aspect["name"]] = aspect_default_value(aspect)
        return values

    def create_empty_entry(
            self,
            entry_type: ENTRY_TYPES_LITERAL,
            *,
            actors: List[dict],
            template: EntryRef,
            language: str,
            title: Optional[str] = "",
            description: Optional[str] = "",
            privacy: Literal["public", "private"] = PUBLIC,
            license: str = "CC0",
            slug: str = None,
            values: dict = frozenset(),
            uuid: Optional[UUID] = None,
    ) -> EntryRegular:
        # todo check if template type and type of this entry make sense...
        # todo also check if a slug is required and passed
        if not uuid:
            uuid = uuid4()
        template_data = template.dict()
        template_version = template.version
        template_obj = self.root_sw.template_codes.get_by_slug_lang(template.slug, language)
        if not values:
            values = self.template_default_values(template_obj)

        domain = template_obj.domain

        return EntryRegular.parse_obj({
            TEMPLATE: template_data,
            DESCRIPTION: description,
            TEMPLATE_VERSION: template_version,
            "values": values,
            TYPE: entry_type,
            SLUG: slug,
            LICENSE: license,
            PRIVACY: privacy,
            TITLE: title,
            ENTRY_REFS: [],
            TAGS: {} if entry_type == REGULAR else [],
            STATUS: "published",
            UUID: uuid,
            VERSION: 0,
            LANGUAGE: language,
            "location": None,
            "actors": actors,
            DOMAIN: domain,
            "creation_ts": datetime.now(),
            "attached_files": [],
        })

    def create_empty_regular(
            self,
            *,
            template: EntryRef,
            actors: List[dict],
            language: str,
            title: Optional[str] = "",
            description: Optional[str] = "",
            privacy: Optional[Literal["public", "private"]] = PUBLIC,
            license: Optional[str] = "CC0"
    ) -> EntryRegular:
        return self.create_empty_entry(
            title=title,
            description=description,
            entry_type=REGULAR,
            template=template,
            actors=actors,
            privacy=privacy,
            license=license,
            language=language,
        )

    # for tag in tags
    # todo, maybe tags should be created as models already and this part takes care of creating the relationships

    def entries_to_model(
            self,
            entries: List[Entry],
            model: Union[Type[EntryOut], Type[CodeTemplateMinimalOut]],
    ) -> List[Union[EntryOut, CodeTemplateMinimalOut]]:
        return [self.to_model(e, model) for e in entries]

    def create_share_link(self, entry: Entry) -> str:
        share_access_key, access_key_hash = uuid_and_hash()
        entry.config[ACCESS_KEY_HASH] = access_key_hash
        flag_modified(entry, "config")
        self.db_session.commit()
        url = (
                env_settings().HOST
                + f"/entry?uuid={str(entry.uuid)}&eak={share_access_key}"
        )
        return url

    # noinspection PyMethodMayBeStatic
    def share_access_key_is_valid(
            self, entry: Entry, access_key: UUID, password: Optional[str]
    ):
        if not verify_hash(str(access_key), entry.config.get(ACCESS_KEY_HASH, "")):
            raise ApplicationException(HTTP_403_FORBIDDEN)
        return True

    def revoke_share_link(self, entry: Entry) -> bool:
        """
        un-share an entry by removing  the share-link access-key
        @param entry:
        @return: true if the access_key_hash was in the config and is removed
        """
        if "access_key_hash" in entry.config:
            del entry.config[ACCESS_KEY_HASH]
            flag_modified(entry, "config")
            self.db_session.commit()
            return True
        return False

    # todo actor shouldn't be Optional but Visitor instead of None
    def post_create(
            self,
            actor: Optional[RegisteredActor],
            entry: Entry,
            context: Optional[dict] = None,
    ):
        """
        @param actor:
        @param entry:
        @param context: some additional data
        @return:
        """
        if not context:
            context = {}

        # order...:
        # 1. check user.config.entry.after_create
        if not actor:
            actor = self.root_sw.actor.get_visitor()
        if actor:
            after_create_actions = actor.configs.get("entry", {}).get(
                "after_create", []
            )
            for action in after_create_actions:
                self.run_action(action, actor, entry, context)
        # 2. check entry.template->rules.after_create

        # 3. check entry.domain->entry.after_create
        # self.root_sw.domain.crud_read_meta(entry.domain)
        # 4. check [domain]:no_domain->entry.after_create
        after_create_actions = (
            self.root_sw.domain.crud_read_meta(NO_DOMAIN)
                .content.get("entry", {})
                .get("after_create", [])
        )
        for action in after_create_actions:
            self.run_action(action, actor, entry, context)

    # noinspection PyMethodMayBeStatic
    def run_action(
            self,
            action: dict,
            actor: Optional[RegisteredActor],
            entry: Entry,
            context: Optional[dict] = None,
    ):
        if not context:
            context = {}
        # should be done during init...
        action_o = EntryAction.parse_obj(action)
        if action_o.type == "call_plugin":
            plugin_name = action_o.properties.get("plugin_name")
            if plugin_name not in registered_plugins:
                raise ApplicationException(
                    400, f"plugin :{plugin_name} not in the list of registered plugins"
                )
            registered_plugins[plugin_name](actor=actor, entry=entry, context=context)

    def lang_entry_update_dict(self, slug: str, lang_code: str) -> dict:
        lang_entry = self.root_sw.template_codes.get_by_slug_lang(slug, lang_code)

        base_entry: dict = EntryOut.from_orm(lang_entry.template).dict(
            exclude={TITLE, DESCRIPTION}
        )
        lang_data = {
            ASPECTS: lang_entry.aspects,
            VALUES: lang_entry.values,
            **{TITLE: lang_entry.title, DESCRIPTION: lang_entry.description},
        }

        base_data = EntryLangUpdate.parse_obj(base_entry).dict(exclude_none=True)
        return extract_diff(deep_merge(base_data, lang_data), base_entry)

    def get_model_type(
            self, entry: Entry
    ) -> Union[Type[EntryOut], Type[TemplateBaseInit], Type[TemplateMerge]]:
        if entry.type in BASE_SCHEMA_ENTRIES:
            return TemplateBaseInit
        elif entry.type in CONCRETE_ENTRIES:
            return TemplateMerge
        else:
            return EntryOut

    # noinspection PyMethodMayBeStatic
    def add_has_entry_access_hash(self,
                                  entry: Union[EntryMeta, MapEntry, Dict], db_obj: Entry, actor: RegisteredActor
                                  ):
        if db_obj.has_write_access(actor) and (eak := db_obj.config.get(ACCESS_KEY_HASH)):
            if not entry.rules:
                entry.rules = {"has_entry_access_hash": True}
