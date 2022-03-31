from logging import getLogger
from os.path import join
from typing import List, Dict, Optional, Union, Tuple

from fastapi import APIRouter, Depends, Body, Query, UploadFile, File
from pydantic import Field
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.status import HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from app.dependencies import is_admin, get_sw
from app.models.schema.response import simple_message_response, GenResponse
from app.models.schema.translation_models import (
    ContractedMessageBlock,
    LanguageStatus,
    UserGuideMappingFormat,
)
from app.services.service_worker import ServiceWorker
from app.settings import L_MESSAGE_COMPONENT, env_settings, BASE_LANGUAGE_DIR
from app.util.consts import MESSAGE_TABLE_INDEX_COLUMN
from app.util.controller_utils import delete_temp_file
from app.util.exceptions import ApplicationException
from app.util.files import create_temp_csv, JSONPath, frictionless_extract

router = APIRouter(prefix="/language", tags=["Language"])

logger = getLogger(__name__)


@router.get("/get_component")
def get_component(
        component: L_MESSAGE_COMPONENT,
        languages: List[str] = Query(None),
        structured: bool = Query(
            True, description="converts the table into a structured json object"
        ),
        sw: ServiceWorker = Depends(get_sw),
) -> Union[
    FileResponse, Dict[str, dict], List[List[str]]
]:  # structured or unstructured

    query_languages = sw.messages.get_component_language_filter(languages)
    msgs: Optional[List[List[str]]] = sw.messages.get_component(
        component, query_languages
    )

    if not msgs:
        raise ApplicationException(HTTP_404_NOT_FOUND, "language not found")
    if structured:
        return sw.messages.structure_messages(query_languages, msgs)
    else:
        return msgs


@router.get("/get_component_as_csv")
async def get_component_as_csv(
        component: L_MESSAGE_COMPONENT,
        languages: List[str] = Query(None),
        sw: ServiceWorker = Depends(get_sw),
):
    query_languages = sw.messages.get_component_language_filter(languages)
    msgs: Optional[List[List[str]]] = sw.messages.get_component(
        component, query_languages
    )
    if not msgs:
        raise ApplicationException(HTTP_404_NOT_FOUND, "language not found")
    msgs_dicts = []
    for msg in msgs:
        row = {MESSAGE_TABLE_INDEX_COLUMN: msg[0]}
        for (index, lang) in enumerate(query_languages):
            row[lang] = msg[index + 1]
        msgs_dicts.append(row)

    columns = [MESSAGE_TABLE_INDEX_COLUMN] + query_languages
    temp_file = await create_temp_csv(columns, msgs_dicts)
    filename = f"{env_settings().PLATFORM_TITLE}_{component}_{'_'.join(languages)}.csv"

    return FileResponse(
        temp_file.name,
        filename=filename,
        background=BackgroundTask(delete_temp_file, file_path=temp_file.name),
    )


@router.post("/update_component", deprecated=True)
def update_component(
        component: L_MESSAGE_COMPONENT,
        language: str,
        words: Dict[str, str] = Body(...),
        sw: ServiceWorker = Depends(get_sw),
) -> simple_message_response:
    sw.messages.update_words(component, words, language)
    return sw.msg_response("language.table_update")


# not used in the FE
@router.get("/get_missing_messages")
def get_missing_messages(
        component: L_MESSAGE_COMPONENT,
        language: str,
        source_languages: Optional[List[str]] = Query([]),
        sw: ServiceWorker = Depends(get_sw),
):
    res = sw.messages.get_missing_words(component, language, source_languages)
    return res


@router.post("/add_new_word", dependencies=[Depends(is_admin)])
def add_new_word(
        component: L_MESSAGE_COMPONENT,
        new_word: ContractedMessageBlock,
        sw: ServiceWorker = Depends(get_sw),
):
    """
    this will not be common (so it requires an admin)
    """
    sw.messages.add_new_word(component, new_word.index, new_word.translations)


@router.post("/add_translations")
def add_translations(
        component: L_MESSAGE_COMPONENT,
        translations: List[ContractedMessageBlock],
        sw: ServiceWorker = Depends(get_sw),
):
    """
                           description="A ContractedMessageBlock contains an index "
                                       "and a dict of translations: lang:word"
    """
    sw.messages.add_translations_for_component(component, translations)


@router.post("/update_messages")
def update_messages(
        component: L_MESSAGE_COMPONENT,
        language: str,
        messages: List[Tuple[str, Optional[str]]],
        sw: ServiceWorker = Depends(get_sw),
):
    sw.messages.update_component_for_one_language(component, language, messages)
    return sw.msg_response("messages.submitted")


@router.post("/update_messages_from_csv")
async def update_messages_from_csv(
        component: L_MESSAGE_COMPONENT,
        language: str,
        file: UploadFile = File(...),
        sw: ServiceWorker = Depends(get_sw),
        _=Depends(is_admin),
):
    # this writes and reads again, but is the best way to handle all csv related stuff (encoding, quote, delimiter, ...)
    if file.content_type not in ["text/csv", ""]:
        raise ApplicationException(
            422, f"Wrong file format. Received: {file.content_type}"
        )
    try:
        # read the file as lines
        lines = await frictionless_extract(file.file)

        if lines[0][0] != MESSAGE_TABLE_INDEX_COLUMN and len(lines[0]) > 2:
            raise ApplicationException(
                422,
                "Provide either an 'index_', <landcode> header or only use 2 columns",
            )

        if len(lines[0]) > 2:
            logger.info("multi-column file. need to select, proper column")
            lang_index = lines[0].index(language)
            # assuming index_ is at 0
            lines = list(map(lambda line: [line[0], line[lang_index]], lines))
        if lines[0][0] == MESSAGE_TABLE_INDEX_COLUMN:
            lines = lines[1:]

        sw.messages.update_component_for_one_language(component, language, lines)

    except (TypeError, ValueError) as err:
        logger.error(err)
        raise err
    return sw.msg_response("messages.submitted")


@router.get("/search")
def search_language(search_query: str, sw: ServiceWorker = Depends(get_sw)):
    res = sw.messages.search_language(search_query)
    languages = [{"value": lang[0], "text": lang[1]} for lang in res]
    return {"languages": languages}


@router.get("/all_added_languages")
def get_all_added(sw: ServiceWorker = Depends(get_sw)):
    return {"languages": sw.messages.get_added_languages()}


@router.get("/get_all_languages_statuses")
def get_all_languages_statuses(sw: ServiceWorker = Depends(get_sw)):
    return {"languages": sw.messages.get_all_statuses()}


@router.post("/add_language")
def add_language(language_code: str, sw: ServiceWorker = Depends(get_sw)):
    sw.messages.add_language(language_code)
    return sw.msg_response("messages.language_added")


@router.get("/get_language_names")
def get_language_names(lang_code: str, sw: ServiceWorker = Depends(get_sw)):
    return sw.messages.get_language_names(lang_code)


@router.get("/asses_completeness")
def asses_completeness(language_code: str, sw: ServiceWorker = Depends(get_sw)):
    """
    make a completion test for language: check fe,be, domains and entries
    @param language_code:
    @param sw:
    @return:
    """
    if language_code not in sw.messages.get_added_languages():
        raise ApplicationException(HTTP_404_NOT_FOUND, "Language not yet added")
    return sw.translation.asses_completion(language_code)


@router.get("/language_status")
def get_language_status(lang_code: str, sw: ServiceWorker = Depends(get_sw)):
    language_status = sw.messages.get_lang_status(lang_code)
    if language_status:
        return GenResponse(data=LanguageStatus.from_orm(language_status))
    else:
        return simple_message_response(f"EN:No status for language {lang_code}")


@router.post("/change_language_status")
def change_language_status(
        lang_code: str,
        active: bool,
        sw: ServiceWorker = Depends(get_sw),
        _=Depends(is_admin),
):
    language_active = sw.messages.change_lang_status(lang_code, active)
    return GenResponse(
        msg=f"EN:status for language {lang_code} changed to {'active' if language_active else 'inactive'}",
        data={"active": language_active},
    )


@router.delete("/{language_code}")
def change_language_status(
        language_code: str, sw: ServiceWorker = Depends(get_sw), _=Depends(is_admin)
):
    if not sw.messages.has_language(language_code):
        raise ApplicationException(HTTP_404_NOT_FOUND, "EN:Language does not exist")
    # check if language exists for any domain
    domains_in_lang = sw.domain.crud_read_dmetas_dlangs(
        languages={language_code}, only_active=False, fallback_language=False
    )
    if domains_in_lang:
        raise ApplicationException(
            HTTP_409_CONFLICT,
            msg="Domains defined in this language. delete those first",
            data={"domains": [domain.meta.name for domain in domains_in_lang]},
        )
    sw.messages.delete_language(language_code)
    return GenResponse(msg="EN: language deleted")


@router.get("/user_guide_url")
async def user_guide_url(language_code: str, sw: ServiceWorker = Depends(get_sw)):
    return {"url": sw.translation.get_user_guide_link(language_code)}


@router.get("/get_history")
async def get_history(
        language_code: str,
        component: L_MESSAGE_COMPONENT,
        page: int = 0,
        words_per_page: int = 100,
        sw: ServiceWorker = Depends(get_sw),
):
    return sw.messages.get_history(
        language_code,
        component,
        page,
        words_per_page,
        ["index", "lang_code", "component"],
    )


@router.get(
    "/get_fallback_language_mapping", description="currently used for the user-guides"
)
async def get_history(sw: ServiceWorker = Depends(get_sw)):
    return sw.request.app.state.user_guides_mapping


@router.post(
    "/set_fallback_language_mapping", description="currently used for the user-guides"
)
async def get_history(
        data: UserGuideMappingFormat, sw: ServiceWorker = Depends(get_sw)
):
    sw.request.app.state.user_guides_mapping = data
    JSONPath(join(BASE_LANGUAGE_DIR, "user_guides_mapping.json")).write(
        data.dict(), pretty=True
    )
    return sw.msg_response("entry.updated")
