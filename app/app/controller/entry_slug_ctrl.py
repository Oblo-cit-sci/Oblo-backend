from logging import getLogger
from typing import List, Tuple, Optional

from deprecated.classic import deprecated
from fastapi import Depends, Query, UploadFile, File, APIRouter
from pydantic import Extra
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.dependencies import (
    get_current_actor,
    get_sw,
    get_current_entry,
)
from app.models.orm import RegisteredActor
from app.models.schema import aspect_models, EntryMainModel
from app.models.schema.entry_schemas import EntryOut
from app.models.schema.response import GenResponse, simple_message_response
from app.models.schema.template_code_entry_schema import (
    TemplateBaseInit,
    TemplateMerge, TemplateLang,
)
from app.services.service_worker import ServiceWorker
from app.settings import env_settings
from app.util.consts import (
    LANGUAGE,
    TYPE,
    CONFIG,
    TEMPLATE,
    DOMAIN,
    SLUG,
    MESSAGE_TABLE_INDEX_COLUMN,
    DRAFT,
    ACTORS,
    VERSION,
    LICENSE,
    PRIVACY,
    UUID,
    TEMPLATE_VERSION,
    ASPECTS,
    VALUES,
    TITLE,
    DESCRIPTION, RULES,
)
from app.util.controller_utils import delete_temp_file
from app.util.dict_rearrange import (
    dict2row_iter,
    dict2index_dict,
    flat_dicts2dict_rows,
    merge_flat_dicts,
)
from app.util.files import create_temp_csv
from app.util.language import table_col2dict

router = APIRouter(prefix="/slug/{slug}", tags=["Template and codes"])

logger = getLogger(__name__)


@router.get("/", name="get a base or language entry")
async def get_slug_lang(
        slug: str,
        language: Optional[str] = Query(None),
        domain_default_lang_fallback: Optional[bool] = False,
        sw: ServiceWorker = Depends(get_sw),
):
    if not language:
        entry = sw.template_codes.get_base_schema_by_slug(slug)
        return sw.entry.to_model(entry, TemplateBaseInit)
    if domain_default_lang_fallback:
        logger.warning("with fallback")
        entries = sw.template_codes.get_by_slug_lang_domain_default_fallback(
            slug, language
        )
        # TODO this should also include tag-codes
        if len(entries) > 1:  # default lang included
            entry = entries[0] if entries[0].language == language else entries[1]
        else:
            entry = entries[0]
    else:
        entry = sw.template_codes.get_by_slug_lang(slug, language)
    return sw.entry.to_model(entry, EntryOut)


@router.delete("/")
async def delete_slug_lang(
        slug: str,
        language: Optional[str] = None,
        sw: ServiceWorker = Depends(get_sw),
        current_entry: TemplateMerge = Depends(get_current_entry),
        actor: RegisteredActor = Depends(get_current_actor)
):
    entry = sw.state.current_db_entry
    # if language:
    #     entry = sw.template_codes.get_by_slug_lang(slug, language)
    # else:
    #     entry = sw.template_codes.get_base_schema_by_slug(slug)
    sw.entry.check_has_write_access(entry, actor)
    sw.tag.delete_tags(entry)
    try:
        sw.db_session.delete(entry)
        sw.db_session.commit()
        # todo: delete folder if base
        # delete_entry_folder(entry)
    except:
        return sw.error_response(
            HTTP_500_INTERNAL_SERVER_ERROR, msg="entry.delete_fail"
        )

    return sw.msg_response("entry.delete_ok")


@router.post("/")
async def post_patch(
        slug: str,
        entry: EntryMainModel,
        sw: ServiceWorker = Depends(get_sw),
        current_entry: TemplateMerge = Depends(get_current_entry),
        actor: RegisteredActor = Depends(get_current_actor),
):
    pass


@router.get("/with_references", name="get a base or language entry with its destination (code) entries")
async def get_with_references(
        slug: str,
        language: str,
        domain_default_lang_fallback: bool = False,
        sw: ServiceWorker = Depends(get_sw),
):
    result_entries = []
    if domain_default_lang_fallback:
        logger.warning("with fallback")
        entries = sw.template_codes.get_by_slug_lang_domain_default_fallback(
            slug, language
        )
        # TODO this should also include tag-codes
        if len(entries) > 1:  # default lang included
            entry = entries[0] if entries[0].language == language else entries[1]
        else:
            entry = entries[0]
    else:
        entry = sw.template_codes.get_by_slug_lang(slug, language)
    result_entries.append(entry)
    result_entries.extend(sw.template_codes.get_destination_references(entry))
    # todo. there is a method for that no?
    return [sw.entry.to_model(entry, EntryOut) for entry in result_entries]


@deprecated(reason="Check if table2 results in the same")
@router.get("/aspects_as_index_table")
async def entry_aspects_index_table(
        slug: str,
        language: str,
        sw: ServiceWorker = Depends(get_sw),
        user: RegisteredActor = Depends(get_current_actor),
        current_entry: TemplateMerge = Depends(get_current_entry),
):
    # todo: this should be simplifiable!? by only using EntryLang model...
    # lang_entry = sw.template_codes.get_by_slug_lang(slug, language)
    # get the right version, so it wont crash
    current_entry_dict = TemplateLang.from_orm(current_entry).dict(exclude_none=True)
    lang_data = {
        ASPECTS: current_entry_dict[ASPECTS],
        VALUES: current_entry_dict[VALUES],
        **{
            TITLE: current_entry_dict[TITLE],
            DESCRIPTION: current_entry_dict[DESCRIPTION],
        },
    }
    return GenResponse(
        data={
            "messages": list(dict2row_iter(lang_data)),
            "outdated": current_entry.template.outdated,
        }
    )


@router.get("/update_aspects_as_index_table")
async def entry_aspects_index_table(
        slug: str, language: str, sw: ServiceWorker = Depends(get_sw)
):
    update_entry = sw.entry.lang_entry_update_dict(slug, language)
    return GenResponse(
        data={"messages": list(dict2row_iter(update_entry)), "outdated": True}
    )


@router.get("/as_csv")
async def entry_as_csv(
        slug: str,
        languages: List[str] = Query(None),
        include_base: bool = False,
        sw: ServiceWorker = Depends(get_sw),
):
    entries = sw.template_codes.get_by_slug_langs(slug, languages)

    # sort them by the language-order in the parameters
    entries_flat = []
    for lang in languages:
        found = False
        for e in entries:
            if e.language == lang:
                # include base/merge data in order to have a proper order of fields (TODO only required when we have the base!)
                if lang == languages[0]:
                    base_exclude = {
                        LANGUAGE,
                        TYPE,
                        ACTORS,
                        UUID,
                        PRIVACY,
                        LICENSE,
                        VERSION,
                        CONFIG,
                        TEMPLATE,
                    }
                    entries_flat.append(
                        dict2index_dict(
                            TemplateMerge.from_orm(e).dict(
                                exclude_none=True, exclude=base_exclude
                            )
                        )
                    )
                    if include_base:
                        base_entry = sw.template_codes.get_base_schema_by_slug(slug)
                        entries_flat.append(
                            dict2index_dict(
                                TemplateBaseInit.from_orm(base_entry).dict(
                                    exclude_none=True, exclude=base_exclude
                                )
                            )
                        )

                # language data
                lang_data = TemplateLang.from_orm(e).dict(
                    exclude_none=True,
                    exclude={
                        TEMPLATE_VERSION, PRIVACY, LICENSE, UUID, RULES,
                        LANGUAGE, TYPE, CONFIG, TEMPLATE, DOMAIN, SLUG},
                )
                entries_flat.append(dict2index_dict(lang_data))
                found = True

        if not found:
            entries_flat.append({})
            logger.info(f"adding empty column for language: {lang}")
    # merge with merge data (EntryCodeTemplate model) to keep good order (merge has a good order)
    # logger.warning(f"{len(entries_flat)}, {['merge', 'base'] + languages}")
    columns = ["merge"]
    if include_base:
        columns.append("base")
    columns.extend(languages)
    merged_dicts = merge_flat_dicts(columns, entries_flat)
    # logger.warning(f"merged_dicts: {merged_dicts}")

    # kick the merge out before flattening
    for index_language in merged_dicts.values():
        del index_language["merge"]
        # kick out non language values
        if not include_base:
            for lang in languages:
                if index_language[lang] is None:
                    del index_language[lang]
    result = flat_dicts2dict_rows(merged_dicts)

    final_columns = [MESSAGE_TABLE_INDEX_COLUMN]
    if include_base:
        final_columns.append("base")
        final_result = result
    else:
        # include only language rows
        final_result = []
        for row in result:
            if languages[0] in row:
                final_result.append(row)
    final_columns.extend(languages)
    # print(result)
    temp_file = await create_temp_csv(final_columns, final_result)
    filename = f"{env_settings().PLATFORM_TITLE}_{slug}_{'_'.join(languages)}.csv"

    return FileResponse(
        temp_file.name,
        filename=filename,
        background=BackgroundTask(delete_temp_file, file_path=temp_file.name),
    )


# todo merge post and patch
@router.post("/from_flat")
async def post_from_flat(
        slug: str,
        language: str,
        data: List[Tuple[str, str]],
        actor: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    data.append((LANGUAGE, language))
    entry = sw.template_codes.post_patch_entry_lang_from_flat(slug, data, actor)
    if entry.status == DRAFT:
        return simple_message_response(msg="EN:draft saved")
    else:
        entry_out = sw.entry.to_model(entry, EntryOut)
        return GenResponse(data=entry_out, msg="EN:entry updated")


@router.post("/from_csv")
async def post_from_csv(
        slug: str,
        language: str,
        file: UploadFile = File(...),
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
):
    # logger.warning("post_from_csv")
    data = await sw.translation.read_csv_file_as_translation_list(file.file, language)
    entry = sw.template_codes.post_patch_entry_lang_from_flat(slug, data, actor)
    entry_out = sw.entry.to_model(entry, EntryOut)
    return GenResponse(data=entry_out, msg="EN:entry updated")


@router.post("/base_from_csv")
async def base_from_csv(
        file: UploadFile = File(...),
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
):
    try:
        data = await sw.translation.read_csv_file_as_list(file.file)
        structured_data = table_col2dict(data)
        aspect_models.AspectBaseIn.__config__.extra = Extra.ignore
        base_data = TemplateBaseInit.parse_obj(structured_data).dict(exclude_none=True)
        aspect_models.AspectBaseIn.__config__.extra = Extra.forbid
        return GenResponse(data=base_data)
    except Exception as err:
        logger.warning(err)
    return "fail"


@router.get("/get_entry_of_version")
async def get_entry_of_version(
        slug: str,
        language: str,
        version: int,
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
        current_entry=Depends(get_current_entry),
):
    return GenResponse(
        data=sw.template_codes.get_version(current_entry, version).dict(
            exclude_none=True
        )
    )


@router.post("/")
async def create_template_slug(
        base_data: TemplateBaseInit,
        lang_data: Optional[TemplateMerge],
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
):
    # validate
    # domain, must exist
    # template: should be a schema for value, and empty

    domain_meta = sw.domain.crud_read_meta(base_data.domain)

    entry = sw.data.init_base_entry(base_data, actor, domain_meta)
    if lang_data:
        lang_entry = sw.data.lang__get_model__merge_insert_o_update(
            entry, lang_data.dict(exclude_none=True), actor
        )
        return "top"
    return "top"


@router.post("/util/split_entry2base_lang")
async def post_split_entry(
        data: TemplateMerge,
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
):
    from helper import template_code_transformer

    base, lang = template_code_transformer.split_template_code(data, sw)
    return GenResponse(
        data={
            "base": base.dict(exclude_none=True),
            "lang": lang.dict(exclude_none=True),
        }
    )
