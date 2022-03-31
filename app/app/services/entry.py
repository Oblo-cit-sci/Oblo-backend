import os
import shutil
from datetime import datetime
from logging import getLogger
from os import makedirs
from os.path import isdir, isfile, join
from typing import Dict, List, Optional, Union, Literal, Set
from uuid import UUID

from PIL import Image
from fastapi import UploadFile
from pydantic.types import UUID4
from sqlalchemy import or_, text, func, and_
from sqlalchemy.orm import (
    Query,
    Session,
    aliased,
    contains_eager,
    joinedload,
    selectinload,
)

from app import settings
from app.models.orm import Actor, RegisteredActor, Tag, Entry
from app.models.orm.entry_orm import Entry
from app.models.orm.relationships import (
    ActorEntryAssociation as AEAsc,
    EntryEntryAssociation,
    ActorEntryAssociation,
)
from app.models.schema import EntryMeta, EntrySearchQueryIn, AbstractEntry, TemplateMerge, TemplateBaseInit
from app.models.schema.entry_schemas import PaginatedEntryList, EntryOut
from app.models.schema.template_code_entry_schema import TemplateLang
from app.services.service_worker import ServiceWorker

from app.services.util.aspect import get_aspect_of_type, Unpacker
from app.settings import env_settings
from app.util.common import guarantee_list, guarantee_set
from app.util.consts import (
    ACTOR,
    BEFORE_TS,
    CREATOR,
    PUBLIC,
    PUBLISHED,
    REGULAR,
    TAGS,
    TEMPLATE,
    TITLE,
    DOMAIN,
    LANGUAGE,
    STATUS,
    LIT_ENTRY_STATUSES,
    PUBLISHED_OR_EDITOR,
    REQUIRES_REVIEW,
    DRAFT,
    ACTORS, TYPE, SLUG,
)
from app.util.exceptions import ApplicationException
from app.util.location import only_public_location

logger = getLogger(__name__)


def query_entry_base(
        db_session: Session, current_actor: RegisteredActor, include_draft: bool = False
):
    # todo this AEAsc should be replaced by checking if the current_actor is
    if current_actor:
        query = (
            db_session.query(Entry)
                .join(Entry.actors)
                .filter(
                or_(
                    Entry.public,
                    AEAsc.actor_id == current_actor.id,
                    current_actor.is_admin,
                )
            )
        )
        # todo this filter is not optimal as it might be overwritten (e.g. basic_ctrl.init_data only
        # uses published entries)

        if include_draft:
            # noinspection PyUnresolvedReferences
            query = query.filter(
                or_(
                    Entry.status.in_([PUBLISHED, DRAFT]),
                    and_(Entry.status == REQUIRES_REVIEW, current_actor.is_editor),
                )
            )
        else:
            query = query.filter(
                or_(
                    Entry.status == PUBLISHED,
                    and_(Entry.status == REQUIRES_REVIEW, current_actor.is_editor),
                )
            ).options(contains_eager(Entry.actors))
            # todo can be taken out? doesnt fix the broken, limit issue.
            # ... we limit the entries of a search but get even less,
            # cuz entries have more actors, so it counts actors on entries
            # and not just entries...
        return query
    else:
        return db_session.query(Entry).filter(Entry.public, Entry.status == PUBLISHED)


def join_status_filter(
        query: Query, statuses: Set[LIT_ENTRY_STATUSES] = (PUBLISHED,)
) -> Query:
    # noinspection PyUnresolvedReferences
    return query.filter(Entry.status.in_(list(statuses)))


def join_entrytype_filter(
        query: Query,
        entrytypes: Set[Literal["template", "regular", "code", "base_template", "base_code", "schema"]] = (REGULAR,)
) -> Query:
    # noinspection PyUnresolvedReferences
    return query.filter(Entry.type.in_(entrytypes))


def join_actor_filter(query: Query, actor: Actor) -> Query:
    of_actor_alias = aliased(AEAsc)
    return query.join((of_actor_alias, Entry.actors)).filter(
        of_actor_alias.actor_id == actor.id
    )


def join_language_filter(query: Query, languages: List[str]) -> Query:
    # noinspection PyUnresolvedReferences
    return query.filter(Entry.language.in_(languages))


def join_template_slug_filter(query: Query, template_slugs: List[str]) -> Query:
    entry_template = aliased(Entry)
    return query.join(entry_template, Entry.template).filter(
        entry_template.slug.in_(template_slugs)
    )


def join_domain_filter(query: Query, domain_names: List[str]) -> Query:
    # noinspection PyUnresolvedReferences
    return query.filter(Entry.domain.in_(domain_names))


def simple_query_filter(query, key, value):
    # noinspection PyRedundantParentheses
    return query.filter(text("%s=:value" % (key))).params(value=value)


def has_location_filter(query):
    return query.filter(or_(Entry.location != None,
                            Entry.geojson_location != None))


def entries_query_builder(
        sw: ServiceWorker,
        current_actor: RegisteredActor = None,
        search_query: Optional[EntrySearchQueryIn] = None,
        entrytypes: Set[Literal["template", "regular", "code"]] = frozenset("regular"),
        join_objects: Set[Literal["tags", "actors"]] = ("tags", "actors"),
        include_operator: Literal["or", "and"] = "or",
        include_draft: bool = False,
) -> Query:
    query = query_entry_base(sw.db_session, current_actor, include_draft)
    query = query.options(selectinload("template"))
    if TAGS in join_objects:
        query = query.options(joinedload("tags"))
        query = query.options(joinedload("tags.tag"))
    if ACTORS in join_objects:
        query = query.options(joinedload("actors.actor"))
    language = sw.messages.default_language
    if entrytypes:
        query = join_entrytype_filter(query, entrytypes)
    if search_query:
        for required in search_query.required:
            name = required.name
            value = required.value
            if name == ACTOR:
                # change  required.registered_name -> value
                of_actor = sw.actor.crud_read(value)
                query = join_actor_filter(query, of_actor)
            elif name == PUBLISHED_OR_EDITOR:
                query = query.filter(
                    or_(Entry.status == PUBLISHED, current_actor.is_editor == True)
                )
            elif name == STATUS:
                query = join_status_filter(query, guarantee_set(value))
            elif name == LANGUAGE:
                query = join_language_filter(query, guarantee_list(value))
            elif name == TEMPLATE:
                query = join_template_slug_filter(query, value)
            elif name == DOMAIN:
                query = join_domain_filter(query, guarantee_list(value))
            elif name == BEFORE_TS:
                query = query.filter(Entry.creation_ts > value)
        inclusion_queries = []
        inclusion_groups = {}
        for include in search_query.include:
            name = include.name
            value = include.value
            group = include.search_group
            logger.debug(f"include search: ({name}): {value}")
            q = None
            if name == DOMAIN:
                # noinspection PyUnresolvedReferences
                q = Entry.domain.in_(value)
                inclusion_queries.append(q)
            elif name == TEMPLATE:
                entry_template = aliased(Entry)
                query.join(entry_template, Entry.template)  # todo can this go?
                # noinspection PyUnresolvedReferences
                inclusion_queries.append(Entry.slug.in_(value))
                # join required codes...
                query.join(
                    EntryEntryAssociation,
                    entry_template.id == EntryEntryAssociation.source_id,
                )
                q = and_(
                    entry_template.id == EntryEntryAssociation.source_id,
                    Entry.id == EntryEntryAssociation.destination_id,
                    EntryEntryAssociation.reference["ref_type"].astext == "tag",
                )
            elif name == TITLE:
                # words need to follow each other
                title_search = " & ".join(value.strip().split())
                # noinspection PyUnresolvedReferences
                q = Entry.title.match(title_search)
            elif name == TAGS:
                # in this case we search by the tag filter, so search by value
                if type(value) == list:
                    # noinspection PyUnresolvedReferences
                    q = Entry.entry_tags.any(Tag.value.in_(value))
                else:
                    # in this case we search for one string and we should check the local tag titles
                    title_search = " & ".join(value.strip().split())
                    # q = Entry.entry_tags.any(Tag.text[lang].astext.match(title_search))
                    # todo use unidecode to make it accent agonistic
                    # noinspection PyUnresolvedReferences
                    q = Entry.entry_tags.any(
                        or_(
                            Tag.value.match(title_search),
                            func.lower(Tag.text[language].astext).match(title_search),
                        )
                    )
            else:
                logger.warning(f"unknown include entry-filter {name}")
                continue
            if not group:
                inclusion_queries.append(q)
            else:
                inclusion_groups.setdefault(group, []).append(q)
        for group_name, group_queries in inclusion_groups.items():
            inclusion_queries.append(or_(*group_queries))
            logger.debug(f"included a group: {group_name}")
        if len(inclusion_queries) > 0:
            logger.debug(f"inclusion of {len(inclusion_queries)}")
            if include_operator == "and":
                query = query.filter(and_(*inclusion_queries))
            else:
                query = query.filter(or_(*inclusion_queries))

    return query


def entries_response_paginated(
        count: int,
        entries: List[EntryMeta],
        limit: int,
        offset: int,
        all_uuids: Optional[List[UUID]] = None,
) -> PaginatedEntryList:
    prev_offset, next_offset = prev_next_offset(count, limit, offset)
    return PaginatedEntryList(
        count=count,
        entries=entries,
        prev_offset=prev_offset,
        next_offset=next_offset,
        ts=datetime.now(),
        all_uuids=all_uuids,
    )


def get_entry_path(entry: Union[UUID4, str]):
    return join(settings.ENTRY_DATA_FOLDER, str(entry))


def get_attachment_path(entry_uuid: UUID4, file_uuid: UUID4):
    attachment_path = join(get_entry_path(entry_uuid), str(file_uuid))
    if isfile(attachment_path):
        return attachment_path
    else:
        return None


def get_file_path(entry_slug: str, file_name: str):
    attachment_path = join(get_entry_path(entry_slug), file_name)
    if isfile(attachment_path):
        return attachment_path
    else:
        return None


def guarantee_entry_directory(entry_uuid: UUID4):
    path = get_entry_path(entry_uuid)
    if not isdir(path):
        makedirs(path)


def save_for_entry(entry_uuid: UUID4, file_uuid: UUID4, file: UploadFile):
    guarantee_entry_directory(entry_uuid)
    img = Image.open(file.file)
    img = img.convert("RGB")
    img.thumbnail((1920, 1080))
    file_path = join(get_entry_path(entry_uuid), str(file_uuid))
    img.save(file_path, "PNG")


def delete_entry_folder(entry_uuid: UUID4):
    entry_path = get_entry_path(entry_uuid)
    if isdir(entry_path):
        shutil.rmtree(entry_path)


def delete_entry_attachment(entry_uuid: UUID4, file_uuid: UUID4):
    file_path = join(get_entry_path(entry_uuid), str(file_uuid))
    if isfile(file_path):
        os.remove(file_path)
        return True
    else:
        return False


def prev_next_offset(count, limit, offset):
    prev = None
    next = None
    if offset > 0:
        prev = max(offset - limit, 0)
    if offset + limit < count:
        next = offset + limit
    return prev, next


def set_template(data: Dict, session: Session):
    if data.get("template", None):
        if isinstance(data["template"], Entry):
            logger.warning("called for a 2nd time")
            return True
        template = session.query(Entry).filter(Entry.slug == data["template"]).first()
        if not template:
            raise ApplicationException(
                500,
                f"template not found: {data['template']} required by {data['title']}",
            )
        else:
            data["template"] = template
            return True


# noinspection PyDefaultArgument
def add_with_actor(
        sw: ServiceWorker,
        entry: Entry,
        actor: RegisteredActor,
        refs: List[EntryEntryAssociation] = [],
):
    session = sw.db_session

    # entry.post_init()

    def set_template(raise_error: bool = True):
        # todo reuse this for get entry reference function
        # template should previously also be able to contain the languaage
        if entry.template:
            logger.debug(f"looking for template: {entry.template}")
            template: Optional[Entry] = None
            if isinstance(entry.template, Entry):
                return
            elif isinstance(entry.template, str):
                template = (
                    session.query(Entry)
                        .filter(
                        Entry.slug == entry.template, Entry.language == entry.language
                    )
                        .one_or_none()
                )
                if not template:
                    logger.warning(
                        f"Template for {entry.slug}/{entry.language} not available"
                    )
                    template = (
                        session.query(Entry)
                            .filter(
                            Entry.slug == entry.template,
                            Entry.language == env_settings().DEFAULT_LANGUAGE,
                        )
                            .one_or_none()
                    )
                    if not template:
                        logger.warning(
                            f"Template for {entry.slug}/{entry.language} not available in default language: {env_settings().DEFAULT_LANGUAGE}"
                        )
                        template = (
                            session.query(Entry)
                                .filter(Entry.slug == entry.template)
                                .first()
                        )
                        if not template:
                            logger.exception(
                                f"There is no template available with he name: {entry.template} for entry: {entry.slug}"
                            )
                            if raise_error:
                                raise ApplicationException(
                                    500,
                                    f"There is no template available with he name: {entry.template} for entry: {entry.title}",
                                )
            entry.template = template

    set_template()
    session.add(entry)
    ass = ActorEntryAssociation(actor_id=actor.id, role=CREATOR)
    for ref in refs:
        session.add(ref)
    ass.actor = actor
    ass.entry = entry
    session.add(ass)


def set_as_visitor_entry(entry: Entry):
    entry.privacy = PUBLIC
    entry.license = "CC0"


def clean_construct(Modeltype, e):
    if type(e) == dict:
        d_iter = e.items()
    else:
        d_iter = e.__dict__.items()
    return Modeltype.construct(
        **{k: v for (k, v) in d_iter if k in Modeltype.__fields__}
    )


# def marshal_entry(entry: Entry) -> EntryMeta:
"""
experimental function to create EntryMeta, ... faster than pydantic. not used atm
"""


def make_entry_ref(
        db_session: Session,
        src_entry: Entry,
        dest_id: Union[str, UUID],
        ref_type: Literal["code", "tag"],
) -> Optional[EntryEntryAssociation]:
    dest_entry: Optional[Entry] = None

    if type(dest_id) == str:
        dest_entry = db_session.query(Entry).filter(Entry.slug == dest_id).one_or_none()
    else:
        dest_entry = db_session.query(Entry).filter(Entry.uuid == dest_id).one_or_none()
    if not dest_entry:
        logger.warning(
            f"Cannot make reference from {src_entry.title} to {dest_id}. Destination entry does not exist"
        )
        return None
    else:
        logger.warning("fix Entry-Entry-Assoc...")
        reference = EntryEntryAssociation(
            source=src_entry,
            destination=dest_entry,
            reference_type=ref_type,
            reference={},
        )
        db_session.add(reference)
        return reference


def update_entry_references(db_session: Session, entry: Entry, ref_data: Dict):
    exising_refs: List[EntryEntryAssociation] = entry.entry_refs
    remove_existing: List[EntryEntryAssociation] = exising_refs[:]
    for (ref_dest, ref_type) in ref_data.items():
        for exist_ref in exising_refs:
            if (type(ref_dest) == UUID and exist_ref.destination.uuid == ref_dest) or (
                    type(ref_dest) == str and exist_ref.destination.slug == ref_dest
            ):
                remove_existing.remove(exist_ref)
                break
        else:
            # print(entry.title, ref_dest,ref_type)
            ref = make_entry_ref(db_session, entry, ref_dest, ref_type)
            if ref:
                print(entry.title, ref.destination)
                logger.info(
                    f"Adding reference from: {entry.title} to {ref.destination.title} of type: {ref_type}"
                )

    for rem in remove_existing:
        db_session.delete(rem)


def fix_location_aspect(em: EntryOut, db_obj: Entry, actor: RegisteredActor):
    if not db_obj.protected_read_access(actor):
        aspect_names = get_aspect_of_type(db_obj, "location")
        # todo just the simple version, straight aspect name. no aspect-location stuff
        for aspect in aspect_names:
            value = db_obj.values[aspect]
            unpacked = Unpacker(value)
            if not unpacked.get_unpacked():
                continue
            em.values[aspect] = unpacked.pack(
                only_public_location(unpacked.get_unpacked())
            )


def entry_descriptor(e: Union[Entry, AbstractEntry, TemplateMerge, dict]):
    res = []
    for k in DOMAIN, TYPE, SLUG, LANGUAGE:
        if type(e) in [Entry, TemplateBaseInit, TemplateLang, TemplateMerge]:
            if hasattr(e, k):
                res.append(getattr(e, k))
            else:
                res.append("--")
        elif type(e) is dict:
            res.append(e.get(k, "--"))
        else:
            logger.warning("unknown type")
    return "/".join(filter(lambda v: v, res))