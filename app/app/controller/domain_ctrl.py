from logging import getLogger
from typing import List, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Query, File, UploadFile
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.status import HTTP_409_CONFLICT, HTTP_401_UNAUTHORIZED

from app.controller_util.auth import actor_not_user
from app.dependencies import get_db, get_current_actor, is_admin, get_sw
from app.models.orm import RegisteredActor
from app.models.schema.domain_models import DomainOut, DomainMetaInfoOut, DomainLang
from app.models.schema.entry_schemas import EntryOut
from app.models.schema.template_code_entry_schema import CodeTemplateMinimalOut
from app.models.schema.response import GenResponse, simple_message_response
from app.services.domain_sw import Domainmeta_domainlang
from app.services.service_worker import ServiceWorker
from app.settings import env_settings
from app.util.consts import MESSAGE_TABLE_INDEX_COLUMN, LANGUAGE
from app.util.controller_utils import delete_temp_file
from app.util.dict_rearrange import (
    dict2row_iter,
    extract_diff,
    dict2index_dict,
    flat_dicts2dict_rows,
    merge_flat_dicts,
)
from app.util.exceptions import ApplicationException
from app.util.files import create_temp_csv

router = APIRouter(prefix="/domain", tags=["Domain"])

logger = getLogger(__name__)


@router.get("/", response_model=GenResponse[List[DomainOut]])
async def domains_in_language(
        language: str,
        sw: ServiceWorker = Depends(get_sw),
):
    """
    # todo maybe rename or user a more generic endpoint
    Get all domains in a given language
    @param language:
    @param sw:
    @return:
    """
    domains = sw.domain.get_all_domains(language)
    return GenResponse(data=domains)


@router.post("/{domain_name}/from_flat")
async def post_flat(
        domain_name: str,
        language: str,
        data: List[Tuple[str, str]],
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
        _: Session = Depends(get_db),
):
    if not actor.editor_for_or_admin(domain_name, language):
        raise ApplicationException(HTTP_409_CONFLICT,
                                   "EN:You are not allowed to edit this domain"
                                   )
    (
        domain_meta_lang,
        active_changed,
    ) = sw.domain.post_patch_domain_lang_from_flat(domain_name, language, data, actor)

    if not sw.messages.has_language(language):
        sw.messages.add_language(language)

    if domain_meta_lang.lang.is_active:
        if active_changed:
            msg = "EN:Domain is complete"
        else:
            msg = "EN:domain updated"
        return GenResponse(
            msg=msg, data=DomainOut.parse_obj(sw.domain.domain_data(domain_meta_lang))
        )
    else:
        # some might turn it incomplete again... strange case tho
        if active_changed:
            return simple_message_response(msg="EN:Domain is now incomplete")
        else:
            return simple_message_response(msg="EN:domain updated")


@router.post("/{domain_name}/from_csv")
async def post_from_csv(
        domain_name: str,
        language: str,
        file: UploadFile = File(...),
        sw: ServiceWorker = Depends(get_sw),
        actor: RegisteredActor = Depends(get_current_actor),
        _: Session = Depends(get_db),
):
    if not actor.editor_for_or_admin(domain_name, language):
        raise ApplicationException(HTTP_409_CONFLICT,
                                   "EN:You are not allowed to edit this domain"
                                   )

    data = await sw.translation.read_csv_file_as_translation_list(file.file, language)

    (
        domain_meta_lang,
        active_changed,
    ) = sw.domain.post_patch_domain_lang_from_flat(domain_name, language, data, actor)

    if domain_meta_lang.lang.is_active:
        if active_changed:
            msg = "EN:Domain is complete"
        else:
            msg = "EN:domain updated"
        return GenResponse(
            msg=msg, data=DomainOut.parse_obj(sw.domain.domain_data(domain_meta_lang))
        )
    else:
        # some might turn it incomplete again... strange case tho
        if active_changed:
            return simple_message_response(msg="EN:Domain is now incomplete")
        else:
            return simple_message_response(msg="EN:domain updated")


@router.get(
    "/{domain_name}/info",
    response_model=GenResponse[List[DomainOut]],
    response_model_exclude_none=True,
)
async def domain_types(
        domain_name: str = Query(..., description="Domain name"),
        language: Optional[str] = Query(
            [], description="languages. If not given, all languages"
        ),
        sw: ServiceWorker = Depends(get_sw),
):
    domain = sw.domain.get_domain(domain_name, [language])
    return GenResponse(data=domain)


@router.delete("/{domain_name}")
async def delete_domain_lang(
        domain_name: str,
        language: str,
        sw: ServiceWorker = Depends(get_sw),
        admin: RegisteredActor = Depends(is_admin),
):
    dmeta_dlang = sw.domain.crud_read_dmeta_dlang(domain_name, language, True)
    if dmeta_dlang.meta.default_language == language:
        if len(dmeta_dlang.meta.languages) > 1:
            raise ApplicationException(
                HTTP_409_CONFLICT,
                "EN:This is the default language, Delete other language first",
            )

    codes_templates = sw.domain.get_codes_templates(domain_name, language, admin, False)
    if codes_templates:
        raise ApplicationException(
            HTTP_409_CONFLICT,
            "EN:There are codes/templates for this language. delete those first",
        )
    sw.db_session.delete(dmeta_dlang.lang)

    if dmeta_dlang.meta.default_language == language:
        dmeta_dlang.meta.is_active = False

    sw.db_session.commit()

    return GenResponse(
        msg="EN:Domain deleted", data={"domain_name": domain_name, language: language}
    )


@router.delete("/meta/{domain_name}")
async def delete_domain(
        domain_name: str,
        sw: ServiceWorker = Depends(get_sw),
        _: RegisteredActor = Depends(is_admin),
):
    dmeta = sw.domain.crud_read_meta(domain_name, True)
    if dmeta.languages and dmeta.is_active:
        return GenResponse(
            msg="EN:Domain not deleted",
            data={
                "domain_name": domain_name,
                "languages": list(dmeta.languages),
                "is_active": dmeta.is_active,
            },
        )
    sw.db_session.delete(dmeta)
    sw.db_session.commit()
    await sw.domain.rename_source_folder_to_ignore(domain_name)
    return GenResponse(msg="EN:Domain deleted", data={"domain_name": domain_name})


@router.get(
    "/overviews",
    response_model=GenResponse[List[DomainOut]],
    response_model_exclude_none=True,
)
async def overview(
        language: str = Query(...),
        fallback_language: bool = True,
        user: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    if actor_not_user(user) and env_settings().LOGIN_REQUIRED:
        raise ApplicationException(HTTP_401_UNAUTHORIZED, "EN:Not allowed")
    return GenResponse(
        data=sw.domain.get_all_domains_overview(
            language, fallback_language=fallback_language
        )
    )


@router.get("/{domain_name}/get_codes_templates")
async def get_codes_templates(
        domain_name: str,
        language: str,
        full: bool = True,
        include_draft: bool = True,
        current_actor: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    codes_templates = sw.domain.get_codes_templates(
        domain_name, language, current_actor, include_draft=include_draft
    )
    entries = sw.entry.entries_to_model(
        codes_templates, EntryOut if full else CodeTemplateMinimalOut
    )
    return GenResponse(data=entries)


@router.get("/meta_info", response_model=Dict[str, DomainMetaInfoOut])
async def meta_info(
        domain_names: Optional[List[str]] = Query(None),
        actor: RegisteredActor = Depends(get_current_actor),
        sw: ServiceWorker = Depends(get_sw),
):
    meta_infos: Dict[str, DomainMetaInfoOut] = sw.domain.meta_info2model(
        sw.domain.crud_read_metas(domain_names)
    )
    for domain_name, domain_meta_info in meta_infos.items():
        # e = sw.domain.get_codes_templates(domain_name, actor=actor)
        domain_meta_info.all_codes_templates = [
            e.slug for e in sw.domain.get_codes_templates(domain_name, actor=actor)
        ]
    return meta_infos


@router.get("/domain_content_as_index_table")
async def index_table(
        domain_name: str,
        language: str = Query(env_settings().DEFAULT_LANGUAGE),
        sw: ServiceWorker = Depends(get_sw),
):
    dmeta_dlang: Domainmeta_domainlang = sw.domain.crud_read_dmeta_dlang(
        domain_name, language
    )
    # logger.warning(dmeta_dlang)
    dm_data = {"content": dmeta_dlang.meta.content}
    d_data = {
        "content": {**dmeta_dlang.lang.content},
        **{"title": dmeta_dlang.lang.title},
    }
    res = GenResponse(data=list(dict2row_iter(extract_diff(d_data, dm_data))))
    return res


#
# @router.get("/domain_js_plugin")
# async def domain_js_plugin(domain_name: str):
#     pass


@router.get("/{domain_name}/as_csv")
async def domain_as_csv(
        domain_name: str,
        languages: List[str] = Query(...),
        sw: ServiceWorker = Depends(get_sw),
):
    dmeta_dlangs = sw.domain.crud_read_dmetas_dlangs(languages, [domain_name])
    flat_dicts = []

    for lang in languages:
        # get dmeta_dlang of that language
        res_list = list(filter(lambda dmeta_dlang: dmeta_dlang.lang.language == lang, dmeta_dlangs))
        if res_list:
            dmeta_dlang = res_list[0]
            domain_lang = DomainLang.from_orm(dmeta_dlang.lang).dict(exclude_none=True,
                                                                     exclude={LANGUAGE, "domainmeta", "is_active"})
            flat_dict = dict2index_dict(domain_lang)
            flat_dicts.append(flat_dict)
        else:
            flat_dicts.append({})

    result = flat_dicts2dict_rows(merge_flat_dicts(languages, flat_dicts))

    columns = [MESSAGE_TABLE_INDEX_COLUMN] + languages
    temp_file = await create_temp_csv(columns, result)

    filename = (
        f"{env_settings().PLATFORM_TITLE}_{domain_name}_{'_'.join(languages)}.csv"
    )

    return FileResponse(
        temp_file.name,
        filename=filename,
        background=BackgroundTask(delete_temp_file, file_path=temp_file.name),
    )


@router.post("/{domain_name}/{active}")
async def activate(
        domain_name: str,
        active: bool,
        _: RegisteredActor = Depends(is_admin),
        sw: ServiceWorker = Depends(get_sw),
):
    return sw.domain.set_domainmeta_active(domain_name, active)


@router.get("/{domain_name}/get_missing")
async def activate(
        domain_name: str,
        language: str,
        _: RegisteredActor = Depends(is_admin),
        sw: ServiceWorker = Depends(get_sw),
):
    return sw.domain.get_domain_lang_missing(domain_name, language)
