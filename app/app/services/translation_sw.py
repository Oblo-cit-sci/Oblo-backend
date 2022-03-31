import os
from logging import getLogger
from os.path import join
from tempfile import SpooledTemporaryFile
from typing import Optional, List, Tuple

from jsonpath import jsonpath
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.models.orm import Entry
from app.models.orm.relationships import EntryTranslation
from app.services.service_worker import ServiceWorker
from app.settings import (
    BACKEND_MESSAGE_COMPONENT,
    FRONTEND_MESSAGE_COMPONENT,
    env_settings,
    INIT_DATA_FOLDER,
)
from app.util.common import jsonpath2index_string
from app.util.consts import NO_DOMAIN, MESSAGE_TABLE_INDEX_COLUMN, LANGUAGE
from app.util.exceptions import ApplicationException
from app.util.files import read_orjson, frictionless_extract

logger = getLogger(__name__)


class TranslationService:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    def create_translation(
        self, e1: Entry, e2: Entry, commit: bool = True
    ) -> EntryTranslation:
        if e1.translation_id and e2.translation_id:
            if e1.translation_id != e2.translation_id:

                raise ApplicationException(
                    HTTP_500_INTERNAL_SERVER_ERROR,
                    f"both entries are already in a translation group: {e1}, {e2}",
                )
            else:
                return e1.translations
        if e1.translation_id:
            e1.translation_group.entries.append(e2)
        elif e2.translation_id:
            e2.translation_group.entries.append(e1)
        else:
            return EntryTranslation(entries=[e1, e2])
        if commit:
            self.db_session.commit()

    def get_translations(self, entry: Entry) -> List[EntryTranslation]:
        return entry.translations if entry.translation_id else []

    def is_language_index(self, index: str) -> bool:
        return index.endswith(("text", "title", "description", "label"))

    def create_translation_tuples(
        self,
        data: dict,
        jsonpath_expr: str = "$..",
        text_header: Optional[str] = None,
        contain_only_text_only_indices: bool = False,
    ) -> List[Tuple[str, str]]:
        """
        @param contain_only_text_only_indices:
        @param data: A dictionary (e.g. entry or domain)
        @param text_header:
        @param jsonpath_expr: jsonpath expression, which should be converted to tuple (default: '$..' complete data)
        @return:
        """
        paths = jsonpath(data, jsonpath_expr, "PATH")
        paths = [MESSAGE_TABLE_INDEX_COLUMN] + [jsonpath2index_string(p) for p in paths]
        texts = [text_header] + jsonpath(data, jsonpath_expr, "VALUE")
        results = list(filter(lambda t: isinstance(t[1], str), zip(paths, texts)))
        if contain_only_text_only_indices:
            results = list(filter(lambda t: self.is_language_index(t[0]), results))
        return results

    def asses_completion(self, language_code: str):

        incomplete = {}
        no_domain_domain_obj = self.root_sw.domain.crud_read_domain(
            NO_DOMAIN, language_code, False
        )
        if not no_domain_domain_obj:
            incomplete["domain.no_domain"] = "not started"
        else:
            if not no_domain_domain_obj.is_active:
                incomplete["domain.no_domain"] = "incomplete"

        other_domains = self.root_sw.domain.crud_read_dmetas_dlangs(
            languages={language_code}, only_active=False
        )
        for domainmeta_domain in other_domains:
            if (domain_name := domainmeta_domain.meta.name) == NO_DOMAIN:
                continue
            if not domainmeta_domain.domain.is_active:
                incomplete[f"domain.{domain_name}"] = "incomplete"
            required_entries = domainmeta_domain.meta.content.get(
                "required_entries", []
            )
            for required_entry_slug in required_entries:
                entry = self.root_sw.template_codes.get_by_slug_lang(
                    required_entry_slug, language_code, False
                )
                if not entry:
                    incomplete[f"entry.{required_entry_slug}"] = f"missing"
                else:
                    pass
                    # todo a check for completeness?
                    # missing = validate_complete_texts(entry.aspect)
        be_messages = self.root_sw.messages.get_component(
            BACKEND_MESSAGE_COMPONENT, [language_code]
        )
        missing = list(filter(lambda index_msg: not index_msg[1], be_messages))
        if len(missing) > 0:
            incomplete[
                "be_messages"
            ] = f"inclomplete: {len(missing)} of {len(be_messages)} missing"

        fe_messages = self.root_sw.messages.get_component(
            FRONTEND_MESSAGE_COMPONENT, [language_code]
        )
        missing = list(filter(lambda index_msg: not index_msg[1], fe_messages))
        if len(missing) > 0:
            incomplete[
                "fe_messages"
            ] = f"inclomplete: {len(missing)} of {len(fe_messages)} missing"

        return incomplete

    def get_language_names_source_data(self, lang_code: str) -> dict:
        """
        download a json with many names in many languages from some github repo
        and store that file for later
        @param lang_code:
        @return:
        """
        source_file_path = join(
            INIT_DATA_FOLDER, f"languages/source_repo/data/{lang_code}/language.json"
        )
        if os.path.isfile(source_file_path):
            return read_orjson(source_file_path)
        else:
            logger.warning(
                f"There is no language name sourcefile for language: {lang_code}"
            )
            return {}

    def get_language_names_in_one_language(
        self, in_lang: str, languages: List[str]
    ) -> dict:
        """
        @param in_lang:
        @param languages:
        @return:
        """
        language_names_data = self.get_language_names_source_data(in_lang)
        return {l: language_names_data.get(l, None) for l in languages}

    def languagenamne_sourcefile_exists(self, lang_code: str):
        return os.path.isfile(
            join(
                INIT_DATA_FOLDER,
                f"languages/source_repo/data/{lang_code}/language.json",
            )
        )

    def get_one_language_name_in_many_languages(
        self, language: str, in_langs: List[str]
    ):
        return {
            lang: self.get_language_names_source_data(lang).get(language)
            for lang in in_langs
        }

    def get_user_guide_link(self, language_code: str) -> Optional[str]:
        """
        Get the user-guide for a specific language. a mapping file can set a fallback language (mapped language)
        # e.g. catalan -> spanish
        @param language_code:
        @return: url
        """
        try:
            # mapping is stored during start
            mapping_config = self.root_sw.request.app.state.user_guides_mapping
        except AttributeError:
            return env_settings().DEFAULT_USER_GUIDE_URL
        dest_lang = mapping_config.mapping.get(
            language_code, env_settings().DEFAULT_LANGUAGE
        )
        return mapping_config.pages.get(
            dest_lang, env_settings().DEFAULT_USER_GUIDE_URL
        )

    # noinspection PyMethodMayBeStatic
    async def read_csv_file_as_translation_list(
        self, file: SpooledTemporaryFile, language_code: str
    ) -> List[Tuple[str, str]]:
        data = await frictionless_extract(file)
        header = data[0]
        if header[0] != MESSAGE_TABLE_INDEX_COLUMN:
            raise ApplicationException(
                422,
                f"first column must be {MESSAGE_TABLE_INDEX_COLUMN}, but its {header[0]}",
            )
        try:
            language_index = header.index(language_code)
        except ValueError:
            raise ApplicationException(
                422, f"No column that indicated language: {language_code}"
            )
        return [(LANGUAGE, language_code)] + [
            (msg[0], msg[language_index]) for msg in data[1:]
        ]

    # noinspection PyMethodMayBeStatic
    async def read_csv_file_as_list(
        self, file: SpooledTemporaryFile
    ) -> List[Tuple[str, str]]:
        return await frictionless_extract(file)
