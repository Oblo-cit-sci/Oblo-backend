import csv
from collections import Counter
from logging import getLogger
from os.path import isfile, join
from tempfile import NamedTemporaryFile
from typing import Optional, Literal, Union, List

from fastapi import APIRouter, Depends, UploadFile, File, Query, Body, FastAPI
from pydantic import types
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route
from starlette.status import HTTP_404_NOT_FOUND, HTTP_400_BAD_REQUEST

from app.dependencies import get_current_actor, is_admin, get_sw
from app.models.orm import RegisteredActor, Entry
from app.models.schema.entry_schemas import EntryLangOut, EntryOutSignature
from app.models.schema.template_code_entry_schema import TemplateLang
from app.services.service_worker import ServiceWorker
from app.services.template_code_entry_sw import get_local_entry_path, get_relative_path
from app.settings import TEMP_FOLDER, INIT_DOMAINS_FOLDER, env_settings
from app.util.consts import (
    DOMAIN,
    TEMPLATE,
    CODE,
    MESSAGE_TABLE_INDEX_COLUMN,
    BASE_ENTRIES, ACTOR, ENTRY, TYPE, SLUG, LANGUAGE, UUID, TITLE, TEMPLATE_VERSION, PRIVACY, LICENSE, CONFIG, REGULAR,
)
from app.util.controller_utils import delete_temp_file
from app.util.dict_rearrange import table2dict
from app.util.exceptions import ApplicationException
from app.util.files import frictionless_extract, remove_last_empty_column, JSONPath, create_temp_csv
from app.util.language import table_col2dict
from app.util.tree_funcs import tree2csv

router = APIRouter(prefix="/util", tags=["Util"])

logger = getLogger(__name__)


@router.get("/init_data_translation_csv")
async def init_data_translation_csv(
        domain: str,
        type: str,
        slug: str,
        language: str,
        dest_language: Optional[str] = None,
        separator: str = ",",
        sw: ServiceWorker = Depends(get_sw),
):
    """
    @todo: use the actual database data. and make something to get the language stuff from out of the domains....
    couldnt make the deletion happen with a task,
    https://www.starlette.io/background/
    response would always be empty
    @param domain:
    @param type: code|template
    @param slug:
    @param language: code
    @param dest_language: code
    @param separator: , ; ...
    @return: a csv with 3 columns
    """
    try:
        data: dict = sw.data.read_init_file(domain, type, slug, language)
    except FileNotFoundError as err:
        raise ApplicationException(HTTP_404_NOT_FOUND, err)
    if type != DOMAIN:
        data = {"values": data.get("values"), "aspects": data.get("aspects")}
    tuples = sw.translation.create_translation_tuples(
        data, contain_only_text_only_indices=(type in [TEMPLATE, CODE])
    )
    tuples = [(MESSAGE_TABLE_INDEX_COLUMN, language, dest_language)] + tuples
    temp = NamedTemporaryFile("w", -1, encoding="utf-8", newline="\n", delete=False)
    csv_writer = csv.writer(temp, delimiter=separator, quoting=csv.QUOTE_MINIMAL)
    # if dest_language:
    #     tuples[0] = list(tuples[0]) + [dest_language]
    for l in tuples:
        csv_writer.writerow(l)
    filename = "_".join([domain, type, language, slug + ".csv"])
    return FileResponse(temp.name, filename=filename, media_type="text/csv")


@router.get("/translation_csv")
async def translation_csv(
        slug: str = Query(..., description="the slug of the code/template entry"),
        language: str = Query(
            ..., description="The source language of the code/template entry"
        ),
        dest_language: Optional[str] = None,
        separator: str = ";",
        sw: ServiceWorker = Depends(get_sw),
):
    entry = sw.template_codes.get_by_slug(slug, language)
    tuples = sw.translation.create_translation_tuples(
        EntryLangOut.from_orm(entry).dict(exclude_none=True, exclude_unset=True)
    )
    temp = NamedTemporaryFile("w", -1, "utf-8", delete=False)
    csv_writer = csv.writer(temp, delimiter=separator, quoting=csv.QUOTE_MINIMAL)
    if dest_language:
        tuples[0] = list(tuples[0]) + [dest_language]
    for l in tuples:
        # l = list(f'"{cell}"' for cell in l)
        csv_writer.writerow(l)
    filename = "_".join([slug, language + ".csv"])
    return FileResponse(temp.name, filename=filename)


@router.post("/submit_translation_csv")
def submit_translation_csv(
        language: str = Query(..., description="language code, 2chars"),
        slug_name: str = Query(..., description="slug of the entry or name of the domain"),
        is_domain: bool = Query(
            False,
            description="set the interpretation of slug_name, false: entry:slug, true: domain:name",
        ),
        file: UploadFile = File(...),
        current_actor: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    def convert_path(path: str):
        new_p = (
            path.replace("$", "")
                .replace("][", ".")
                .replace("[", "")
                .replace("]", "")
                .replace("]", ".")
                .replace("'", "")
        )
        return new_p

    fn = f"{TEMP_FOLDER}/{file.filename}"
    open(fn, "wb").write(file.file.read())
    reader = csv.DictReader(
        open(fn, encoding="utf-8"), delimiter=";", fieldnames=["path_", language]
    )
    rows = [r for r in reader]

    lines = [(convert_path(r["path_"]), r[language]) for r in rows]
    data = table_col2dict(lines)

    # todo also writes "path_" into the file
    if not is_domain:
        entry = sw.template_codes.get_by_slug(slug_name, language)
        sw.data.get_init_file(
            entry.domain, entry.type, slug_name, language, raise_error=False
        ).write(data)
    else:
        domain = sw.domain.crud_read_dmetas_dlangs(
            languages={language}, names={slug_name}, only_active=False
        )
        if not domain:
            raise ApplicationException(
                HTTP_404_NOT_FOUND,
                f"Domain {slug_name} does not exist",
                data={"name": slug_name},
            )
        sw.data.get_init_file(slug_name, DOMAIN, lang=language).write(data)
    return data


@router.get("/init_slug_entry_in_lang")
async def get_slug_entry_for_init_in_lang(
        slug: str,
        language: str,
        sw: ServiceWorker = Depends(get_sw),
):
    entry = sw.template_codes.get_by_slug_lang(slug, language)
    return TemplateLang.from_orm(entry).dict(exclude_none=True, exclude={
        DOMAIN, TYPE, SLUG, LANGUAGE, UUID, TEMPLATE, TEMPLATE_VERSION, PRIVACY, LICENSE, CONFIG
    })


@router.get("/get_singular_component_message")
async def get_singular_component_message(
        component: str, index: str, language: str, sw: ServiceWorker = Depends(get_sw)
):
    # todo another commit has the same lines in language_ctrl replaced by a sw function
    query_languages = []
    # todo: check if language exists
    # for lang in languages:
    #     # todo fix validation based on existing languages
    #     if lang in []:
    #         logger.warning(f"language: {lang} does not exist")
    #     else:
    #         query_languages.append(lang)
    # if not query_languages:  # not in, ..... accepted_langs:
    #     raise ApplicationException(HTTP_404_NOT_FOUND, "no language is valid")

    msg = sw.messages.t(index, language, component)
    if msg:
        return {"msg": msg}


@router.get("/modules")
async def modules(_=Depends(is_admin)):
    import os

    i_modules = [m.split("==") for m in os.popen("pip freeze").read().split("\n")]
    return {"modules": i_modules}


@router.post("/compare_component_with_csv")
async def compare_component_with_csv(
        component: str,
        csv_file: UploadFile = File(...),
        _: RegisteredActor = Depends(is_admin),
        sw: ServiceWorker = Depends(get_sw),
):
    incoming_data = remove_last_empty_column(await frictionless_extract(csv_file.file))
    incoming_data_languages = incoming_data[0][1:]
    incoming_data_dict = table2dict(incoming_data[0], incoming_data)

    db_data = sw.messages.get_component(component)
    db_data_languages = sw.messages.get_added_languages()
    db_dict = table2dict([MESSAGE_TABLE_INDEX_COLUMN] + db_data_languages, db_data)

    # language difference
    common_languages = set(incoming_data_languages).intersection(db_data_languages)

    # different indices
    incoming_data_index_set = set(incoming_data_dict.keys())
    db_index_set = set(db_dict.keys())
    missing_in_db = db_index_set - incoming_data_index_set
    missing_in_data = incoming_data_index_set - db_index_set

    word_diff = []

    for index in db_dict:
        if index in incoming_data_dict:
            for lang in common_languages:
                input_word = incoming_data_dict[index][lang]
                db_word = db_dict[index][lang]
                if input_word != db_word:
                    word_diff.append((index, lang, input_word, db_word))
    # todo: more...
    return [common_languages, missing_in_db, missing_in_data, word_diff]


@router.get("/exists")
async def exists(
        object_type: Literal["domain", "entry", "actor"],
        identifier: Union[types.UUID, str],
        secondary_identifier: Optional[str] = Query(
            None, description="optional. for domain-language"
        ),
        sw: ServiceWorker = Depends(get_sw),
) -> bool:
    if object_type == DOMAIN:
        return bool(sw.domain.exists(identifier, secondary_identifier))
    elif object_type == ENTRY:
        return sw.entry.exists(identifier)
    elif object_type == ACTOR:
        return sw.actor.exists(identifier)


@router.get(
    "/reload_entry", response_model=EntryOutSignature, response_model_by_alias=True
)
async def reload_template_code_entry(
        slug: str,
        language: Optional[str] = None,
        sw: ServiceWorker = Depends(get_sw),
        admin: RegisteredActor = Depends(is_admin),
) -> Optional[EntryOutSignature]:
    # they will throw a not found if not existing
    if not language:
        existing_entry = sw.template_codes.get_base_schema_by_slug(slug)
    else:
        existing_entry = sw.template_codes.get_by_slug_lang(slug, language)
    local_file_path = get_local_entry_path(existing_entry)
    if isfile(local_file_path):
        domain_meta = sw.domain.crud_read_meta(existing_entry.domain)
        if existing_entry.type in BASE_ENTRIES:
            entry = sw.data.init_base_by_path(local_file_path, admin, domain_meta)
        else:  # CONCRETE_ENTRIES
            path: JSONPath = JSONPath(join(INIT_DOMAINS_FOLDER, local_file_path))
            entry = sw.data.init_concrete_by_path(path, admin, existing_entry)
        if entry:
            entry_signature = EntryOutSignature.from_orm(entry)
            entry_signature.path = get_relative_path(local_file_path)
            return entry_signature
    else:
        sw.error_response(
            HTTP_400_BAD_REQUEST, f"No file for {slug}/{language if language else '--'}"
        )


@router.post("/table2tree")
async def tree2table(slug: str,
                     language: Optional[str] = None,
                     additional_columns_only_for_levels: Optional[List[str]] = Body(None),
                     sw: ServiceWorker = Depends(get_sw)) -> FileResponse:
    """
    :param slug:
    :param language:
    :param additional_columns_only_for_levels: Pass an empty body to get all additional columns for all levels.
    If the body is empty, no additional column will be added
    """
    # when language given get by slug and language
    if language:
        entry = sw.template_codes.get_by_slug_lang(slug, language)
        is_base_tree = False
    else:
        entry = sw.template_codes.get_base_schema_by_slug(slug)
        is_base_tree = True

    header, rows = tree2csv(entry.values,
                            additional_columns_only_for_levels=additional_columns_only_for_levels,
                            is_base_tree=is_base_tree)
    temp_file = await create_temp_csv(header, rows)
    filename = f"{env_settings().PLATFORM_TITLE}_{slug}_tree.csv"

    return FileResponse(
        temp_file.name,
        filename=filename,
        background=BackgroundTask(delete_temp_file, file_path=temp_file.name),
    )


@router.post("/all_endpoints")
async def get_all_routes(request: Request):
    app: FastAPI = request.app
    return [(",".join(r.methods), r.path) for r in app.routes if isinstance(r, Route)]


@router.post("/template_versioning_info")
async def template_versioning_fix(
        template_slug: str,
        sw: ServiceWorker = Depends(get_sw)):

    base_entry = sw.template_codes.get_base_schema_by_slug(template_slug)

    result= {
        "slug": template_slug,
        "base": {
          "uuid": None,
          "version": None,
        },
        "languages": []
    }

    result["base"]["uuid"] = base_entry.uuid
    result["base"]["version"] = base_entry.version

    language_entries = sw.template_codes.get_all_concretes(template_slug)
    for entry in language_entries:

        regulars = sw.template_codes.persist.base_q(language=entry.language, types=[REGULAR])\
            .filter(Entry.template_id == entry.id)
        versioned_entries = {}
        for regular in regulars:
            c = versioned_entries.setdefault(str(regular.template_version), Counter())
            c += Counter({str(regular.template_version): 1})

        result["languages"].append({
            "language": entry.language,
            "uuid": entry.uuid,
            "version": entry.version,
            "template_version": entry.template_version,
            "num_entries": dict(versioned_entries)
        })
    return result


@router.post("/template_versioning_fix")
async def template_versioning_fix(
        template_slug: str,
        language: Optional[str] = None,
        sw: ServiceWorker = Depends(get_sw)):

    pass
