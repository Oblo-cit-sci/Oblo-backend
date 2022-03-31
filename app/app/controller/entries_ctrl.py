from datetime import datetime
from logging import getLogger
from tempfile import NamedTemporaryFile
from typing import List, Optional, Any, Set, Dict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import ArgumentError, ProgrammingError
from sqlalchemy.orm import load_only, Load
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from app.dependencies import get_current_actor, get_sw
from app.controller_util.db import get_entry_count
from app.models.orm import Entry, RegisteredActor
from app.models.schema import EntryMeta, EntrySearchQueryIn, MapEntry, UUIDList
from app.models.schema.entry_schemas import EntryFieldSelection, EntryOut, EntriesDownloadConfig
from app.models.schema.template_code_entry_schema import CodeTemplateMinimalOut
from app.models.schema.response import GenResponse
from app.services.entry import (
    entries_query_builder,
    entries_response_paginated,
    has_location_filter,
)
from app.services.entry_export import process_entry, column_names
from app.services.service_worker import ServiceWorker
from app.services.util.entries2geojson import entries2feature_collection
from app.services.util.entry_search_query_builder import build
from app.settings import env_settings
from app.util.consts import REGULAR, TEMPLATE, SLUG, CODE
from app.util.controller_utils import delete_temp_file
from app.util.exceptions import ApplicationException
from app.util.files import create_temp_csv, zip_files
from app.util.location import set_visible_location

router = APIRouter(prefix="/entries", tags=["Entries"])

logger = getLogger(__name__)


@router.post("/get_uuids", response_model=GenResponse, response_model_exclude_none=True)
async def entries_uuids_query(
    search_query: EntrySearchQueryIn = (),
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    # noinspection PyUnresolvedReferences
    query = entries_query_builder(
        sw,
        current_actor,
        search_query=search_query,
        entrytypes={REGULAR},
        include_operator="and",
    ).order_by(Entry.creation_ts.desc())
    # count = get_entry_count(query)
    # todo doesnt seem to only get the uuid but the whole entry
    all_uuids = [e.uuid for e in query.options(load_only(Entry.uuid)).all()]
    return GenResponse(data=all_uuids)


@router.post("/search")
async def entries_query(
    search_query: EntrySearchQueryIn = (),
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
    limit: int = Query(20, ge=0, le=100),
    offset: int = Query(0, ge=0),
):

    logger.debug("searching entries with: %s @ %s", search_query, datetime.now())
    # noinspection PyUnresolvedReferences
    query = entries_query_builder(
        sw,
        current_actor,
        search_query=search_query,
        entrytypes={REGULAR},
        include_operator="and",
    ).order_by(Entry.creation_ts.desc())
    try:
        count = get_entry_count(query)
    except (ArgumentError, ProgrammingError) as err:
        logger.error("Error counting entries. fallback to slow method:...")
        logger.error(err)
        count = len(query.all())
    logger.info(f"entries-count: {count}")
    entries: List[Entry] = query.offset(offset).limit(limit)
    all_uuids = None
    # todo TRUE !?
    if True or search_query.settings.get("all_uuids", False):
        # todo doesnt seem to only get the uuid but the whole entry
        all_uuids = [e.uuid for e in query.options(load_only(Entry.uuid)).all()]

    entries_out = sw.entry.create_entry_list(entries, current_actor, EntryMeta)

    paginated_entries = entries_response_paginated(
        count, entries_out, limit, offset, all_uuids
    )
    return GenResponse(data=paginated_entries)


@router.post("/map_entries")
async def get_map_entries(
    as_geojson: bool = False,
    search_query: EntrySearchQueryIn = EntrySearchQueryIn(),
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    query = has_location_filter(
        entries_query_builder(
            sw,
            current_actor,
            search_query=search_query,
            entrytypes={REGULAR},
            include_operator="and",
        ).options(Load(Entry))
    )
    # .options(load_only("uuid", "title", "privacy", "status", "location")... TODO later...?
    entries = query.all()
    entries_out: List[MapEntry] = sw.entry.create_entry_list(
        entries, current_actor, MapEntry
    )

    if as_geojson:
        entries_out = entries2feature_collection(entries_out)
    return GenResponse(data={"entries": entries_out, "ts": datetime.now()})


@router.post("/by_uuids")
async def get_entries_by_uuid(
    uuid_list: UUIDList,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
    fields: Optional[EntryFieldSelection] = None,
    limit: int = Query(100, ge=0, le=500),
    offset: int = Query(0, ge=0),
):
    query = entries_query_builder(
        sw, current_actor, entrytypes={REGULAR}, include_operator="and"
    ).filter(Entry.uuid.in_(uuid_list.uuids))
    count = get_entry_count(query)
    entries: List[Entry] = query.offset(offset).limit(limit)
    entries_out = []

    for e in entries:
        if not fields:
            entries_out = sw.entry.create_entry_list(entries, current_actor, EntryMeta)
        else:
            # this is actually useless, since entries_query_builder -> query_entry_base makes 'query(Entry)'
            # query.options(load_only(*field_names))
            field_names = ["uuid"] + [f[0] for f in fields if f]
            e_dict = {field: getattr(e, field) for field in field_names}
            if "location" in field_names:
                set_visible_location(e_dict, e, current_actor)
            if "values" in field_names:
                del e_dict["values"]
            entries_out.append(e_dict)
    if not fields:
        paginated_entries = entries_response_paginated(
            count, entries_out, limit, offset
        )
        return GenResponse(data=paginated_entries)
    else:
        return GenResponse(data=entries_out)


@router.post("/download")
async def download(
    config: EntriesDownloadConfig,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
) -> FileResponse:
    """
    Download entries as a csv file
    """
    # logger.warning(config)
    entries: List[Entry] = (
        entries_query_builder(
            sw, current_actor, search_query=config.search_query, entrytypes={REGULAR}, include_operator="and"
        )
        .filter(Entry.uuid.in_(config.entries_uuids))
        .all()
    )

    if len(entries) > 5000:
        raise ApplicationException(
            422, "EN:Number of entries per download is limited to 5000"
        )
    elif len(entries) == 0:
        raise ApplicationException(422, "EN:No entries to download")

    filtered_entries = []
    logger.debug(f"entries: {entries}")
    templates: Set[Entry] = set()
    template_ids = []
    meta_only = config.select_data == "metadata"
    if meta_only:
        out_type = EntryMeta
        filtered_entries = entries
        for e in entries:
            if e.template_id not in template_ids:
                templates.add(e.template)
    else:
        out_type = EntryOut
        for e in entries:
            if e.template_id not in template_ids:
                templates.add(e.template)
            # logger.warning(
            #     f"{e.title}, {e.template_version}, {next(filter(lambda t: t.id == e.template_id, templates)).version}")
            if (
                next(filter(lambda t: t.id == e.template_id, templates)).version
                == e.template_version
            ):
                filtered_entries.append(e)

    entries_dicts = [
        e.dict()
        for e in sw.entry.create_entry_list(filtered_entries, current_actor, out_type)
    ]
    logger.debug(f"number of entries: {len(entries_dicts)}")
    # slug -> EntryOut.dict
    template_dicts = {
        template.slug: EntryOut.from_orm(template).dict() for template in templates
    }
    # processed entries, based on the template
    entries_result = [
        process_entry(e, template_dicts[e[TEMPLATE][SLUG]], meta_only)
        for e in entries_dicts
    ]

    # slug -> csv files
    temp_files: Dict[str, NamedTemporaryFile] = {}
    # slug -> csv file names
    temp_file_names: Dict[str, str] = {}
    #
    for template in templates or meta_only:
        temp_files[template.slug] = await create_temp_csv(
            column_names(template_dicts[template.slug], meta_only),
            list(
                filter(lambda entry: entry[TEMPLATE] == template.slug, entries_result)
            ),
        )

        temp_file_names[
            template.slug
        ] = f"{env_settings().PLATFORM_TITLE}-entries_download-{template.slug}-{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"

    if len(templates) == 1 or meta_only:
        slug = list(template_dicts.values())[0]["slug"]
        file_response = FileResponse(
            temp_files[slug].name,
            filename=temp_file_names[slug],
            background=BackgroundTask(
                delete_temp_file, file_path=temp_files[slug].name
            ),
        )
        return file_response
    else:
        zip_file = await zip_files(
            "fantastic.zip",
            [
                (file, name)
                for file, name in zip(temp_files.values(), temp_file_names.values())
            ],
        )
        file_response = FileResponse(zip_file.filename, filename="fantastic.zip")

        # return FileResponse(zip_file.filename, filename="fantastic.zip",
        #                     background=BackgroundTask(delete_temp_file, file_path=zip_file.filename))

        return file_response


@router.get("/get_entries_by_slugs", response_model=GenResponse[List])
async def get_entries_by_slugs(
    slugs: List[str] = Query(...),
    language: str = Query(...),
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    entries: List[Entry] = sw.template_codes.get_by_slugs_lang(slugs, language)
    entries_out = []
    for e in entries:
        logger.debug(f"Adding template/code: {e.slug}/{e.language}")
        entries_out.append(sw.entry.to_model(e, EntryOut))
    return GenResponse(data=entries_out)


@router.get("/get_codes_templates")
async def get_codes_templates(
    language: str = Query(...),
    full: bool = Query(True),
    current_actor: RegisteredActor = Depends(get_current_actor),
    sw: ServiceWorker = Depends(get_sw),
):
    entries = entries_query_builder(
        sw,
        current_actor,
        search_query=build(languages=[language]),
        entrytypes={CODE, TEMPLATE},
    ).all()

    entries_models = sw.entry.entries_to_model(
        entries, EntryOut if full else CodeTemplateMinimalOut
    )
    return GenResponse(data=entries_models)
