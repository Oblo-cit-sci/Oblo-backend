from enum import Enum, auto
from logging import getLogger
from os.path import join
from typing import Optional, List, Tuple, Union

from deepdiff import DeepDiff
from deepdiff.model import DiffLevel
from deepmerge.exception import InvalidMerge
from deprecated.classic import deprecated
from pydantic import ValidationError, Extra
from sortedcontainers import SortedList
from sqlalchemy import or_
from sqlalchemy.orm.attributes import flag_modified
from starlette.status import HTTP_404_NOT_FOUND

from app.models.orm import Entry, RegisteredActor, DomainMeta, EntryEntryAssociation
from app.models.schema import (
    EntryRef,
    EntryMainModelTypes,
    EntryMainModel
)
from app.models.schema.aspect_models import ItemMerge, AspectBaseIn, ItemBase
from app.models.schema.template_code_entry_schema import (
    TemplateBaseInit,
    TemplateMerge,
    EntryEntryRef,
    EntryIn, TemplateLang,
)
from app.services.entry import entry_descriptor
from app.services.entry_sw import EntryInModels
from app.services.entry_versioning import EntryVersioningService
from app.services.service_worker import ServiceWorker
from app.settings import INIT_DOMAINS_FOLDER, env_settings
from app.util.consts import (
    SLUG,
    LANGUAGE,
    TYPE,
    VALUE_LIST,
    VALUE_TREE,
    BASE_ENTRIES,
    TEMPLATE,
    UUID,
    PUBLISHED,
    DRAFT,
    VALUES,
    ASPECTS,
    CONFIG,
    FROM_FILE,
    BASE_CODE,
    CODE,
    BASE_TEMPLATE,
    LIT_ENTRY_STATUSES,
    ACTORS,
    TAGS,
    VERSION,
    ENTRY_REFS,
    CONCRETE_ENTRIES,
    TEMPLATE_VERSION,
    RULES,
    LOCATION,
    SCHEMA,
    BASE_SCHEMA_ENTRIES, ATTR,
)
from app.util.dict_rearrange import deep_merge, check_model_active, merge_aspects_one_by_one
from app.util.exceptions import ApplicationException
from app.util.files import JSONPath
from app.util.language import table_col2dict

logger = getLogger(__name__)


class TemplateCodeService:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session
        from app.services.persist.template_code_entry_ps import (
            TemplateCodeEntryPersistService,
        )

        self.persist = TemplateCodeEntryPersistService(root_sw.db_session)
        self.versioning = EntryVersioningService(self)

    def get(self, slug, language: Optional[str] = None, raise_error: bool = True) -> Optional[Entry]:
        if language:
            return self.get_by_slug_lang(slug, language, raise_error)
        else:
            return self.get_base_schema_by_slug(slug, raise_error)

    def get_by_slug_lang(
            self, slug: str, language: str, raise_error: bool = True
    ) -> Optional[Entry]:
        """
        get entries of given slug. if no language is given, get the base entry (no language)
        # todo same as get_base_by_slug
        @param slug:
        @param language:
        @param raise_error:
        @return:
        """
        if not slug and not language:
            raise ApplicationException(
                500,
                f"Cannot get template/code of slug & lang with missing value: {slug} {language}",
            )
        entry = self.persist.base_q(slug=slug, language=language).one_or_none()
        if not entry and raise_error:
            raise_not_found({SLUG: slug, LANGUAGE: language})
        return entry

    def get_by_slugs_lang(self, slugs: List[str], language: str) -> Optional[Entry]:
        if not language:
            language = env_settings().DEFAULT_LANGUAGE
        # noinspection PyUnresolvedReferences
        return (
            self.persist.base_q(language=language).filter(Entry.slug.in_(slugs)).all()
        )

    def get_by_slug_langs(
            self, slug: str, languages: List[str], raise_error: bool = True
    ) -> Optional[Entry]:
        """
        later base-xxx will also have a language, then their type would be the differentiator
        @param slug:
        @param languages:
        @param raise_error:
        @return:
        """
        # noinspection PyUnresolvedReferences
        entries = (
            self.persist.base_q(slug=slug).filter(Entry.language.in_(languages)).all()
        )
        if not entries and raise_error:
            raise_not_found({SLUG: slug, LANGUAGE: languages})
        return entries

    def get_all_concretes(self, slug: str) -> List[Entry]:
        """
        get all language entries for a given slug
        """
        # noinspection PyUnresolvedReferences
        return (
            self.persist.base_q(slug=slug)
                .filter(Entry.type.in_(CONCRETE_ENTRIES))
                .all()
        )

    def get_by_slug_lang_domain_default_fallback(
            self, slug: str, language: Optional[str], raise_error: bool = True
    ) -> Optional[Entry]:
        """
        later base-xxx will also have a language, then their type would be the differentiator
        @param slug:
        @param language:
        @param raise_error:
        @return:
        """
        q = (
            self.persist.base_q(slug=slug)
                .join(DomainMeta, Entry.domain == DomainMeta.name)
                .filter(
                or_(
                    Entry.language == language,
                    Entry.language == DomainMeta.default_language,
                )
            )
        )
        # logger.warning(q.all())
        # TODO BRING IN TAG CODE ENTRIES
        # TODO doesnt seem to work...
        # source = alias(Entry)
        # q = q.filter(Entry.id.in_(source))
        # code = aliased(Entry)
        # q = q.join(EntryEntryAssociation, Entry.id == EntryEntryAssociation.source_id)
        # q = q.filter(Entry.id == EntryEntryAssociation.source_id,
        #              code.id == EntryEntryAssociation.destination_id,
        #              EntryEntryAssociation.reference["ref_type"].astext == "tag")
        entries = q.all()

        # logger.warning(q.all())
        if not entries and raise_error:
            raise_not_found({SLUG: slug, LANGUAGE: language})
        return entries

    # noinspection PyMethodMayBeStatic
    def get_destination_references(self, entry: Entry) -> List[Entry]:
        return [ref.destination for ref in entry.entry_refs]

    def get_base_schema_by_slug(self, slug: str, raise_error: bool = True):
        """
        ONLY USED ONCE... USEFUL?
        get base-entry (no language)
        """
        q = self.persist.base_q(slug=slug)
        # noinspection PyUnresolvedReferences
        q = q.filter(Entry.type.in_(BASE_SCHEMA_ENTRIES))
        e = q.one_or_none()
        if not e and raise_error:
            raise_not_found({SLUG: slug})
        return e

    def merge_base_lang(self, base_model: TemplateBaseInit, lang_model: TemplateLang) -> TemplateMerge:
        base_data = base_model.dict(exclude_none=True, exclude={TEMPLATE, UUID})
        lang_data = lang_model.dict(exclude_none=True)

        try:
            entry_data = deep_merge(
                base_data,
                lang_data,
                True,
            )
        except InvalidMerge as err:
            logger.error(
                f"Merging base and lang failed for {entry_descriptor(base_model)}, {entry_descriptor(lang_model)}"
            )
            logger.error(err)
            if len(base_model.aspects) != len(lang_model.aspects):
                logger.error(
                    f"""Different number aspect. names: {[(i, a.name) for i, a in enumerate(base_model.aspects)]} 
                    ,labels: {[(i, a.label) for i, a in enumerate(lang_model.aspects)]}"""
                )
            else:
                aspect_merge_results = merge_aspects_one_by_one(base_data, lang_data, True)
                logger.exception(aspect_merge_results)

            logger.warning(
                f"If an entry already exists the template_version will remain on the current version"
            )
        else:
            try:

                # logger.debug("merged with base-entry")
                entry_data[TEMPLATE] = {UUID: base_model.uuid, SLUG: base_model.slug}
                full_model = TemplateMerge.parse_obj(entry_data)
                # logger.debug("EntryCodeTemplate parsed")
                # todo maybe move out. implies that the base entry exists...
                full_model.template.version = (
                    self.root_sw.template_codes.resolve_reference(
                        full_model.template
                    ).version
                )
                return full_model
            except ValidationError as err:
                logger.error(
                    f"Merging failed: concrete entrydata  cannot be parsed for  {entry_descriptor(base_model)}, "
                    f"{entry_descriptor(lang_model)}"
                )
                logger.error(err)
                # logger.error(json.dumps(jsonable_encoder(entry_data), indent=2))

    def post_patch_entry_lang_from_flat(
            self, slug: str, data: List[Tuple[str, str]], actor: RegisteredActor
    ) -> Entry:
        """
        @param slug:
        @param data:
        @param actor:
        @return: the entry and its status
        """
        """
        TODO Assumes that the template_version is the latest of the base entry
        change in frontend to only allow translate from lang that are up-to-date
        """
        structured_data = table_col2dict(data)

        entry_base_obj: Entry = self.get_base_schema_by_slug(slug)
        if not entry_base_obj:
            raise ApplicationException(500, "no template")

        structured_data[TYPE] = get_concrete_type_from_base(entry_base_obj.type)

        if entry_base_obj.type in BASE_ENTRIES:
            base_model = TemplateBaseInit.from_orm(entry_base_obj)
        else:
            # basically just dont merge....
            logger.warning("TODO base is schema...")
            logger.error(
                f"cannot derive entry type from template: {entry_base_obj.type}. "
                f"check which special code. setting it to code"
            )
            raise ApplicationException(500, "Could not update entry")

        # logger.warning(structured_data)
        base_data = base_model.dict(exclude_none=True, exclude={TEMPLATE, UUID})
        try:

            entry_data = deep_merge(
                base_data,
                structured_data,
                True,
            )
            entry_data[TEMPLATE] = EntryRef(
                uuid=entry_base_obj.uuid, version=entry_base_obj.version
            )

            res_model = TemplateMerge.parse_obj(entry_data)

            # compare against the entry of the domain default language to set the status (draft or published)
            default_language = self.root_sw.domain.crud_read_meta(
                res_model.domain
            ).default_language
            # that means default language entry needs to be up-to-date
            compare_against = self.get_by_slug_lang(res_model.slug, default_language)
            compare_against = self.root_sw.entry.to_model(
                compare_against, TemplateLang
            )  # self.to_model(compare_against, EntryOut)
            active = check_model_active(
                compare_against,
                res_model,
                {VALUES, ASPECTS},
                f"{res_model.slug}/{res_model.language}",
                throw_warning=True,
            )
            logger.info(f"{entry_descriptor(res_model)} active?: {active})")
            status = PUBLISHED if active else DRAFT
            # update or insert
            existing_entry: Entry = self.get_by_slug_lang(
                entry_data[SLUG], entry_data[LANGUAGE], raise_error=False
            )
            if existing_entry:
                entry_data[CONFIG] = {**existing_entry.config}
                if FROM_FILE in entry_data[CONFIG]:
                    del entry_data[CONFIG][FROM_FILE]
            entry: Entry = self.update_or_insert(res_model, actor, status)
            return entry
        except InvalidMerge as merge_err:
            logger.error(merge_err)
            aspect_merge_results = merge_aspects_one_by_one(base_data, structured_data, True)
            logger.exception(aspect_merge_results)
            raise ApplicationException(
                422, "EN: cannot merge language data with latest base-entry data"
            )
        except Exception as err:
            logger.error(err)
            raise ApplicationException(
                422, "EN: cannot merge language data with latest base-entry data"
            )
        except ValidationError as err:
            logger.error(err)
            raise ApplicationException(422, "EN: cannot parse entry")

    def update_or_insert(
            self,
            entry_model: EntryInModels,
            actor: RegisteredActor,
            status: LIT_ENTRY_STATUSES = PUBLISHED,
    ) -> Entry:

        # todo to a method
        if entry_model.type in [*BASE_ENTRIES, SCHEMA]:
            existing_entry = self.get_base_schema_by_slug(entry_model.slug, False)
        else:
            existing_entry = self.get_by_slug_lang(
                entry_model.slug, entry_model.language, False
            )
        if existing_entry:
            entry = self._update_entry(
                existing_entry,
                entry_model,
                actor,
                {UUID, ACTORS, TEMPLATE, TAGS, VERSION},
                status,
            )
        else:
            entry = self._insert_entry(entry_model, actor, status)
        # POST VALIDATION... not critical
        if entry.type == CODE:
            self.root_sw.codes.validate_icons(entry)
        return entry

    def _insert_entry(
            self, entry_model: EntryInModels, actor: RegisteredActor, status: str
    ):
        identifier = entry_descriptor(entry_model)
        logger.debug(f"new entry: {identifier}")
        # logger.warning(f"{entry_data.get('rules')}, {entry_data.get('values')}")
        try:
            entry_data = entry_model.dict(
                exclude_unset=True, exclude={TEMPLATE, ENTRY_REFS, ACTORS}
            )
            # noinspection PyArgumentList
            entry: Entry = Entry(**entry_data)
            if entry_model.template:
                entry.template = self.resolve_reference(entry_model.template)
                entry.template_version = entry_model.template.version

            entry.entry_refs = self.create_references(entry, entry_model.entry_refs)

            self.root_sw.entry.update_entry_roles(entry, entry_model.actors, actor)
            # todo move it into the model files
            entry.status = status

            self.db_session.add(entry)
            self.db_session.commit()

            logger.info(f"added new entry: {identifier}")
            if entry.type == CODE:
                self.root_sw.tag.udpate_from_entry(entry_model)
            return entry
        except ApplicationException as err:
            logger.error(err)
            logger.error(f"Cannot add {identifier}")
            raise
        except Exception as err:
            logger.error("fatal error")
            logger.error(err)
            logger.error(f"Cannot add {identifier}")
            raise

    def _update_entry(
            self,
            entry: Entry,
            new_model: EntryInModels,
            actor: RegisteredActor,
            ignore_fields: set = frozenset(),
            status: Optional[LIT_ENTRY_STATUSES] = None,
    ):

        l_msg_name = entry_descriptor(entry)
        logger.debug(f"entry object exists for: {l_msg_name}")

        are_equal, changes = compare_models(
            entry, new_model, ignore_fields=ignore_fields
        )

        if are_equal:
            logger.debug(f"No changes in entry: {l_msg_name}")
            return entry
        else:
            logger.info(f"updating {l_msg_name}")
            # logger.info(changes.pretty())
            self.versioning.update_version(entry, new_model)
            # self.evaluate_version_change(changes)
            fields = list(
                filter(
                    lambda field: field not in ignore_fields, EntryIn.__fields__.keys()
                )
            )
            self.update_db_entry_columns(entry, new_model, fields, actor)

            try:
                if entry.type == CODE:
                    # todo go to function. either pass model or change signature
                    self.root_sw.tag.udpate_from_entry(new_model)
                if status:
                    entry.status = status
                self.db_session.commit()
            except ApplicationException as err:
                logger.error(err)
        # update tags
        # self.update_references(existing_obj, self.get_entry_references(entry_data))
        return entry

    def resolve_reference(self, reference: EntryRef) -> Optional[Entry]:
        """
        takes a EntryRef and returns the referenced Entry object if existing.
        :param reference:
        :return:
        """
        if reference.uuid:
            return (
                self.db_session.query(Entry)
                    .filter(Entry.uuid == reference.uuid)
                    .one_or_none()
            )
        elif reference.slug and reference.language:
            return self.get_by_slug_lang(
                reference.slug, reference.language, raise_error=False
            )
        elif reference.slug:
            return self.get_base_schema_by_slug(reference.slug)
        else:
            return None

    def create_references(
            self, e: Entry, references_data: List[EntryEntryRef]
    ) -> List[EntryEntryAssociation]:
        """

        :param e:
        :param references_data:
        :return:
        """
        associations = []
        for ref in references_data:
            try:
                simple_ref = EntryRef(slug=ref.dest_slug, language=e.language)
                ref_entry = self.resolve_reference_with_fallback_language(
                    simple_ref, self.entry_domain_default_language(e)
                )
                associations.append(
                    EntryEntryAssociation(
                        source=e,
                        destination=ref_entry,
                        reference=ref.dict(exclude_none=True),
                    )
                )
            except ApplicationException as err:
                logger.error(
                    f"A reference cannot be created: {e.slug, e.type, e.language} -> {references_data}"
                )
                raise err
            except Exception as err:
                logger.error("Unknown exception")
                logger.error(err)
                logger.error(
                    f"A reference cannot be created: {e.slug, e.type, e.language} -> {references_data}"
                )
                raise err

        return associations

    def update_db_entry_columns(
            self, entry: Entry, new_model: EntryInModels, fields, actor: RegisteredActor
    ):

        modified: List[str] = []
        new_data = new_model.dict(exclude_none=True, exclude={TEMPLATE, ACTORS})

        for field in fields:
            if getattr(entry, field, None) != (new_value := new_data.get(field, None)):
                logger.debug(f"field change: {field}")
                logger.debug(f"{getattr(entry, field, None)} ==> {new_value}")
                try:
                    if field == ENTRY_REFS:
                        entry.entry_refs = self.create_references(
                            entry, new_model.entry_refs
                        )
                    elif field == TEMPLATE_VERSION:
                        entry.template_version = new_model.template.version
                    else:
                        setattr(entry, field, new_value)
                        modified.append(field)
                        if field in [
                            VALUES,
                            ASPECTS,
                            RULES,
                            "attached_files",
                            LOCATION,
                        ]:
                            flag_modified(entry, field)

                except AttributeError as err:
                    logger.error(err)
                    logger.error(f"Could not update field: {field}")
                    raise err
                except Exception as err:
                    logger.error(err)
                    logger.error(
                        f"Something went horribly wrong... Could not update field: {field}"
                    )
                    raise err

        self.root_sw.entry.update_entry_roles(entry, new_model.actors, actor)

    def stash_template_code_extra_config_and_set_to(self, new_extra: Extra):
        current_stash = self.root_sw.state.template_code_config_extra_stash
        if current_stash:
            raise ApplicationException(500, "stash already filled")

        for model_type in [AspectBaseIn, ItemBase, TemplateBaseInit, TemplateLang]:
            current_stash[model_type] = model_type.__config__.extra
            model_type.__config__.extra = new_extra

    def pop_template_code_extra_config_stash(self):
        current_stash = self.root_sw.state.template_code_config_extra_stash
        if not current_stash:
            raise ApplicationException(500, "stash is empty")

        for model_type in [AspectBaseIn, ItemBase, TemplateBaseInit, TemplateLang]:
            model_type.__config__.extra = current_stash[model_type]

        self.root_sw.state.template_code_config_extra_stash = {}

    def resolve_reference_with_fallback_language(
            self, reference: EntryRef, fallback_language: str
    ) -> Optional[Entry]:

        if not reference.slug:
            logger.error(f"no slug given for reference: {reference}")
            raise ApplicationException(
                500, f"no slug given for reference: {reference}"
            )

        reference_entry = self.resolve_reference(reference)
        if reference_entry:
            return reference_entry
        logger.warning(
            f"Reference: {reference} not available. "
            f"Checking entry in default language: {fallback_language}"
        )
        fallback_ref = EntryRef(slug=reference.slug, language=fallback_language)
        reference_entry = self.resolve_reference(fallback_ref)
        if not reference_entry:
            logger.error(
                f"Reference: {fallback_ref} not available in fallback language: {fallback_language}"
            )
            raise ApplicationException(500, f"no slug given for reference: {reference}")

        return reference_entry

    def entry_domain_default_language(self, entry: Entry):
        # todo just one?
        return self.root_sw.domain.crud_read_metas([entry.domain])[0].default_language

    # noinspection PyMethodMayBeStatic
    def get_version(self, entry: Union[TemplateBaseInit, TemplateMerge], version: int) -> EntryMainModel:
        self.versioning.get_version(entry, version)

    def _get_db_entry(self, entry: EntryMainModelTypes) -> Entry:
        # todo maybe also store the db-entry in sw
        return self.root_sw.entry.crud_get(entry.uuid)

    def to_proper_model(self, entry: Entry) -> EntryInModels:
        """
        transforms the entry into the appropriate model
        """
        model = TemplateBaseInit if entry.type in BASE_SCHEMA_ENTRIES else TemplateMerge
        return self.root_sw.entry.to_model(entry, model, True)

    # noinspection PyMethodMayBeStatic
    def evaluate_version_change(self, changes):
        print(changes.tree)
        tree = changes.tree
        t1_changes = ["dictionary_item_removed", "iterable_item_removed", "values_changed"]
        t2_changes = ["dictionary_item_added", "iterable_item_added"]

        class ChangeLevel(Enum):
            UNCRITICAL_ASPECT_CHANGE = auto()
            CRITICAL_ASPECT_CHANGE = auto()
            UNCRITICAL_RULES_CHANGE = auto()
            CRITICAL_RULES_CHANGE = auto()

        def evaluate_aspect_change(keys: List[str], change: DiffLevel):
            # just an example
            if keys[2] == ATTR:
                if keys[3] == "suffix":
                    return ChangeLevel.UNCRITICAL_ASPECT_CHANGE

        for t1_change in t1_changes:

            if tree.get(t1_change):
                for changed_item in tree[t1_change].items:
                    # print(type(changed_item))
                    current = changed_item.all_up
                    keys = []
                    while current.down:
                        param = current.t1_child_rel.param
                        keys.append(param)
                        current = current.down
                    if keys[0] == ASPECTS:
                        evaluate_aspect_change(keys, changed_item)

        for t2_change in t2_changes:
            if tree.get(t2_change):
                for changed_item in tree[t2_change].items:
                    current = changed_item.all_up
                    while current.down:
                        param = current.t2_child_rel.param
                        # print(param)
                        current = current.down


def get_concrete_type_from_base(base_type: str) -> str:
    if base_type not in BASE_ENTRIES:
        ApplicationException(500, f"requested type for base_type: {base_type}")
    return {BASE_CODE: CODE, BASE_TEMPLATE: TEMPLATE}[base_type]


def get_base_type_from_concrete(concrete_type: str) -> str:
    if concrete_type not in CONCRETE_ENTRIES:
        ApplicationException(
            500, f"requested base type for concrete_type: {concrete_type}"
        )
    return {CODE: BASE_CODE, TEMPLATE: BASE_TEMPLATE}[concrete_type]


@deprecated(reason="we only care about duplicates of tags")
def code_entry_validate_unique_values(
        entry: TemplateMerge, raise_error: bool = False
) -> bool:
    """
    @param entry:
    @param raise_error:
    @return: if it has duplicates or not
    """
    l_sorted = SortedList()
    duplicates: set = set()

    schema_slug = entry.rules.code_schema
    allow_duplicates_on_levels = entry.rules.allow_duplicates_on_levels

    # logger.warning(f"{entry.slug}: {allow_duplicates_on_levels}")

    def add(node: ItemMerge, sl: SortedList):
        if (val := node.value) in sl:
            duplicates.add(val)
            logger.warning(f"duplicate from node: {val}")
        # logger.warning(f"existing: {sl}")
        else:
            sl.add(val)

    if schema_slug == VALUE_LIST:
        for v in entry.values.list:
            add(v, l_sorted)
    elif schema_slug == VALUE_TREE:

        def rec_add(n: ItemMerge, level=0):
            if level not in allow_duplicates_on_levels:
                add(n, l_sorted)
            for k in n.children or []:
                rec_add(k, level + 1)

        rec_add(entry.values.root)
    else:
        if raise_error:
            raise TypeError(f"Wrong entry-type. expected code base got: {type(entry)}")
        else:
            logger.warning(f"Values cannot be identified in {entry.slug}")
            return False

    if duplicates:
        logger.warning(f"tag duplicates: {duplicates} for entry: {entry.slug}")
    if duplicates is None or len(duplicates) > 0:
        logger.warning("Not checking for tags")

    return len(duplicates) > 0


def compare_models(
        entry: Entry, new: EntryInModels, ignore_fields: set = frozenset()
) -> (bool, dict):
    if entry.type in [CODE, TEMPLATE]:
        model = TemplateMerge
    else:
        model = TemplateBaseInit
    try:
        aspect_type_pre_validators = None
        if env_settings().MIGRATION_HELP_ACTIVE:
            logger.warning(f"MIGRATION HELP: Removing TemplateBaseInit.aspects.type validation function")
            aspect_type_pre_validators = TemplateBaseInit.__fields__["aspects"].type_.__fields__["type"].pre_validators
            TemplateBaseInit.__fields__["aspects"].type_.__fields__["type"].pre_validators = None
        orig = model.from_orm(entry)
        if env_settings().MIGRATION_HELP_ACTIVE:
            TemplateBaseInit.__fields__["aspects"].type_.__fields__["type"].pre_validators = aspect_type_pre_validators
    except ValidationError:
        logger.error(f"DB entry cannot be parsed")
        raise
    orig_dict, new_dict = (
        m.dict(exclude=ignore_fields, exclude_none=True) for m in (orig, new)
    )

    diff = DeepDiff(orig_dict, new_dict)
    return diff == {}, diff


def raise_not_found(data):
    """
    Raise not found error
    """
    raise ApplicationException(HTTP_404_NOT_FOUND, f"Entry not found", data)


def get_relative_path(path) -> str:
    return JSONPath(path).relative_to(INIT_DOMAINS_FOLDER).as_posix()

def get_local_entry_path(entry: Entry) -> str:
    if entry.language:
        return join(
            INIT_DOMAINS_FOLDER,
            entry.domain,
            "lang",
            entry.language,
            entry.type,
            f"{entry.slug}.json",
        )
    else:
        return join(
            INIT_DOMAINS_FOLDER,
            entry.domain,
            get_concrete_type_from_base(entry.type),
            f"{entry.slug}.json",
        )
