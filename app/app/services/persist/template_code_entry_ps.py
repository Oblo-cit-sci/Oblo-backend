from typing import Optional, List

from sqlalchemy.orm import Query

from app.models.orm import Entry
from app.models.schema import EntryRef
from app.services.persist import PersistService
from app.services.template_code_entry_sw import raise_not_found
from app.settings import env_settings
from app.util.consts import SLUG, LANGUAGE, ENTRY_TYPES_LITERAL
from app.util.exceptions import ApplicationException


class TemplateCodeEntryPersistService(PersistService):
    def __init__(self, db_session):
        super().__init__(db_session)

    def base_q(self, *, slug=None, language=None, types: List[ENTRY_TYPES_LITERAL] = None) -> Query:
        """
        Base query for entries.
        """
        q = self.db_session.query(Entry)
        if slug:
            q = q.filter(Entry.slug == slug)
        if language:
            q = q.filter(Entry.language == language)
        if types:
            # noinspection PyUnresolvedReferences
            q = q.filter(Entry.type.in_(types))
        return q

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
                400,
                f"Cannot get template/code of slug & lang with missing value: {slug} {language}",
            )
        entry = self.base_q(slug=slug, language=language).one_or_none()
        if not entry and raise_error:
            raise_not_found({SLUG: slug, LANGUAGE: language})
        return entry


    def get_by_slugs_lang(self, slugs: List[str], language: str) -> Optional[Entry]:
        if not language:
            language = env_settings().DEFAULT_LANGUAGE
        # noinspection PyUnresolvedReferences
        return self.base_q(language=language).filter(Entry.slug.in_(slugs)).all()

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
        else:
            return None
