import os.path
from collections import namedtuple
from logging import getLogger
from typing import List, Dict, Optional, Tuple, Set

import aiofiles.os
import jsonpath
from fastapi import HTTPException
from sqlalchemy import or_, exists, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import NoResultFound
from starlette.status import HTTP_404_NOT_FOUND, HTTP_422_UNPROCESSABLE_ENTITY

from app.models.orm import Domain, DomainMeta, RegisteredActor
from app.models.schema.domain_models import (
    DomainOut,
    DomainBase,
    DomainLang,
    DomainMetaInfoOut,
    DomainLangContent,
    DomainMinimumLangOut,
)
from app.services.entry import entries_query_builder
from app.services.service_worker import ServiceWorker
from app.services.util.entry_search_query_builder import build
from app.settings import INIT_DOMAINS_FOLDER
from app.util.consts import (
    LANGUAGE,
    NAME,
    DOMAIN,
    CODE,
    TEMPLATE,
    DEFAULT_LANGUAGE,
    TITLE,
    INDEX,
    CONTENT,
    DESCRIPTION,
    IS_ACTIVE,
    Location_validation,
)
from app.util.dict_rearrange import (
    deep_merge,
    validate_complete_texts,
    check_model_active,
)
from app.util.exceptions import ApplicationException

from app.util.language import table_col2dict

logger = getLogger(__name__)

Domainmeta_domainlang = namedtuple("Domainmeta_domain", ["meta", "lang"])


class DomainServiceWorker:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    def crud_read_domain(
            self, name: str, language: str, raise_error: bool = True
    ) -> Domain:
        """
        get a domain object (meta + language data)
        @param name: name of the domain
        @param language: language of the domain
        @param raise_error: raise error if not found (default: True)
        @return: Domain database object
        """
        try:
            # why does the 2nd not work?
            return (
                self.db_session.query(Domain)
                    .options(selectinload("domainmeta"))
                    .filter(
                    Domain.language == language, Domain.domainmeta_id == DomainMeta.id
                )
                    .filter(DomainMeta.name == name)
                    .one()
            )
        except NoResultFound as err:
            if raise_error:
                logger.error(err)
                raise ApplicationException(
                    HTTP_404_NOT_FOUND, "Domain not found", data={"domain_name": name}
                )

    def exists(self, name, language: Optional[str] = None):
        if language:
            return self.db_session.query(
                exists().where(
                    and_(
                        Domain.domainmeta_id == DomainMeta.id,
                        DomainMeta.name == name,
                        Domain.language == language,
                    )
                )
            ).scalar()
        else:
            return self.db_session.query(
                exists().where(DomainMeta.name == name)
            ).scalar()

    def crud_read_meta(self, name: str, raise_error: bool = True) -> DomainMeta:
        """
        get the domain meta object
        @param name: name of the domain
        @param raise_error: raise an error if not found (default: True)
        @return: DomainMeta database object
        """
        try:
            return (
                self.db_session.query(DomainMeta).filter(DomainMeta.name == name).one()
            )
        except NoResultFound as err:
            if raise_error:
                logger.error(err)
                raise ApplicationException(
                    HTTP_404_NOT_FOUND, "Domain not found", data={"domain_name": name}
                )

    def crud_read_metas(self, names: List[str], raise_error: bool = True) -> DomainMeta:
        """
        get the domain meta objects, gets all if there are no names given
        @param names: names of the domains
        @param raise_error: raise an error if not found (default: True)
        @return: DomainMeta database object
        """
        try:
            base = self.db_session.query(DomainMeta)
            if names:
                # noinspection PyUnresolvedReferences
                return base.filter(DomainMeta.name.in_(names)).all()
            else:
                return base.all()
        except NoResultFound as err:
            # todo does this happen, or just empty list?
            if raise_error:
                logger.error(err)
                raise ApplicationException(
                    HTTP_404_NOT_FOUND, "Domain not found", data={"domain_names": names}
                )

    def crud_read_dmeta_dlang(
            self, name: str, language: str, raise_error: bool = True
    ) -> Domainmeta_domainlang:
        """
        Get a domain object and its domain-meta object
        @param name: name of the domain
        @param language: language
        @param raise_error: raise error if not found (default: True)
        @return: Tuple of Domain, Domain-meta database objects
        """
        try:
            return Domainmeta_domainlang(
                *self.db_session.query(DomainMeta, Domain)
                    .filter(
                    Domain.domainmeta_id == DomainMeta.id,
                    DomainMeta.name == name,
                    Domain.language == language,
                )
                    .one()
            )
        except NoResultFound as err:
            if raise_error:
                logger.error(err)
                raise ApplicationException(
                    HTTP_404_NOT_FOUND, "Domain not found", data={"domain_names": name}
                )

    def get_all_meta(self) -> List[DomainMeta]:
        """
        Get all domain-meta objects
        @return: all domain-meta database objects
        """
        return self.db_session.query(DomainMeta).all()

    def crud_read_dmetas_dlangs(
            self,
            languages: Optional[Set[str]] = frozenset(),
            names: Optional[Set[str]] = frozenset(),
            only_active: bool = True,
            fallback_language: bool = True,
    ) -> List[Domainmeta_domainlang]:
        """
        Get a cross-section of a set of domains and a set of languages.  Both are optional, which means all domains
        or languages are included. only active, filters on active domains (checked from meta)
         (todo could also filter active languages, which mean active dlangs?).
        If there is no tuple domainlang for a given domain, it could return the fallback for the domain
        todo rename to only_active_domains,
        @param languages:
        @param names:
        @param only_active:
        @param fallback_language:
        @return:
        """
        base_q = self.db_session.query(DomainMeta, Domain).filter(
            Domain.domainmeta_id == DomainMeta.id
        )
        if only_active:
            base_q = base_q.filter(DomainMeta.is_active)
        if names:
            # noinspection PyUnresolvedReferences
            base_q = base_q.filter(DomainMeta.name.in_(names))
        if languages:
            if fallback_language:
                # noinspection PyUnresolvedReferences
                base_q = base_q.filter(
                    or_(
                        Domain.language.in_(list(languages)),
                        Domain.language == DomainMeta.default_language,
                    )
                )
            else:
                # noinspection PyUnresolvedReferences
                base_q = base_q.filter(Domain.language.in_(list(languages)))
        return [Domainmeta_domainlang(*res) for res in base_q.all()]

    def meta_info2model(
            self, domain_metas: List[DomainMeta]
    ) -> Dict[str, DomainMetaInfoOut]:
        """
        gets the result of metainfo, which is a list of list of the 2 dicts(domainmeta,domain)
        this is used for translation
        @param domain_metas:
        @return: list of DomainMetaInfo
        """
        meta_infos: Dict[str, DomainMetaInfoOut] = {}
        for m in domain_metas:
            mi = DomainMetaInfoOut.from_orm(m)
            mi.required_entries = m.content["required_entries"]
            mi.active_languages = m.get_active_languages()
            mi.inactive_languages = [
                lang for lang in m.languages if lang not in mi.active_languages
            ]
            meta_infos[m.name] = mi
        return meta_infos

    def domain_data(
            self,
            domainmeta_domain_lang: Domainmeta_domainlang,
            full_domain_content: bool = True,
    ) -> DomainOut:
        # logger.warning(domainmeta_domain_lang)
        dmeta = domainmeta_domain_lang.meta
        domain_out = DomainOut(
            **self.root_sw.models.get_as_dict(dmeta, [NAME, INDEX, DEFAULT_LANGUAGE]),
            languages=dmeta.get_active_languages(),
            include_entries=dmeta.content.get("include_entries"),
        )
        dlang = domainmeta_domain_lang.lang
        if full_domain_content:
            domain_out.langs[dlang.language] = {
                NAME: dmeta.name,
                TITLE: dlang.title,
                DESCRIPTION: dlang.content[DESCRIPTION],
                **dlang.content,
            }
        logger.debug(f"domain out: {domain_out}")
        domain_out.overviews[dlang.language] = DomainMinimumLangOut.parse_obj(
            {
                **self.root_sw.models.get_as_dict(dlang, [TITLE]),
                DESCRIPTION: dlang.content[DESCRIPTION],
            }
        )
        return domain_out

    def insert_or_update_meta(self, domainmeta_model: DomainBase) -> DomainMeta:
        existing_meta_obj: DomainMeta = self.crud_read_meta(
            domainmeta_model.name, False
        )
        if not existing_meta_obj:
            # noinspection PyArgumentList
            domain_base = DomainMeta(**domainmeta_model.dict())
            self.db_session.add(domain_base)
            return domain_base
        else:
            self.update_meta(existing_meta_obj, domainmeta_model)
            return existing_meta_obj

    def update_meta(
            self,
            domainmeta_obj: DomainMeta,
            domainmeta_model: DomainBase,
            update_domain_langs: bool = False,
    ):
        changes: Dict = self.root_sw.models.update_obj_from_model(
            domainmeta_obj, domainmeta_model, [NAME, IS_ACTIVE]
        )
        if changes:
            logger.info(
                f"update_domainmeta: {domainmeta_obj.name}, fields: {[changes.keys()]}"
            )
            if "content" in changes and update_domain_langs:
                # todo: merge & update
                logger.warning("domain objects should update")
                pass
        else:
            logger.info(f"update_domainmeta: No changes")

    def insert_or_update_domain(
            self,
            domain_lang_model: DomainLang,
            domainmeta_obj: DomainMeta,
            commit: bool = False,
    ) -> Tuple[Domain, bool, bool]:
        """
        @param domain_lang_model:
        @param domainmeta_obj:
        @param commit:
        @return: domain obj, insert?, active changed? (false when added)
        """
        name = domainmeta_obj.name
        language = domain_lang_model.language
        domain_obj: Domain = self.crud_read_domain(name, language, False)
        # insert
        inserted = False
        active_changed = False
        if not domain_obj:
            inserted = True
            logger.debug(f"inserting domain: {name}/{language}")
            # noinspection PyArgumentList
            domain_obj = Domain(
                **domain_lang_model.dict(exclude={"domainmeta"}),
                domainmeta=domainmeta_obj,
            )
            self.db_session.add(domain_obj)
        else:
            logger.info(f"updating: {name}/{language}")
            changes = self.update_domain(domain_obj, domain_lang_model, domainmeta_obj)
            if IS_ACTIVE in changes:
                active_changed = True
        missing = validate_complete_texts(domain_obj.content)
        if missing:
            logger.warning(f"Domain wording: Some texts are missing: {missing}")
        if commit:
            self.db_session.commit()
        return domain_obj, inserted, active_changed

    def update_domain(
            self,
            existing_domain_obj: Domain,
            domain_lang_model: DomainLang,
            domainmeta_obj: DomainMeta,
    ) -> dict:
        changes: Dict = self.root_sw.models.update_obj_from_model(
            existing_domain_obj,
            domain_lang_model,
            [LANGUAGE],
            {"domainmeta": domainmeta_obj},
        )
        if changes:
            logger.info(
                f"update_domain: {domainmeta_obj.name}, fields: {[changes.keys()]}"
            )
        else:
            logger.info(f"update_domain: No changes")
        return changes

    def get_all_domains_overview(
            self, language, only_active: bool = True, fallback_language: bool = False
    ):
        """
        create a new model DomainBaseOut...

        @param language:
        @param only_active:
        @return:
        """
        domain_langs = [
            d_m
            for d_m in self.crud_read_dmetas_dlangs(
                languages={language},
                only_active=only_active,
                fallback_language=fallback_language,
            )
        ]
        domain_langs = self.filter_fallbacks(domain_langs, language)
        return [
            self.domain_data(d_m, full_domain_content=False) for d_m in domain_langs
        ]

    def get_all_domains(self, language: str) -> List[DomainOut]:
        """
        get all domains in a given language
        @param language: language code
        @return: A list of complete domain data in the given language
        """
        # TODO NOT WORKING: Domain.name!
        # todo only used in one endpoint
        return [
            self.domain_data(d_m)
            for d_m in self.crud_read_dmetas_dlangs(languages={language})
        ]

    def get_domain(
            self,
            name: str,
            languages: Optional[Set[str]] = frozenset(),
            raise_error: bool = True,
            fallback: bool = True,
    ) -> List[DomainOut]:
        """
        get a single domain in a language
        # todo just called in one endpoint...
        @param name: domain name
        @param languages: language codes
        @param raise_error:
        @param fallback: also include fallback language (default language of domain)
        @return: domain data in the given language
        """
        domain = self.crud_read_dmetas_dlangs(languages, {name}, fallback)
        if not domain:
            if raise_error:
                raise HTTPException(
                    HTTP_404_NOT_FOUND,
                    f"domain not in the language: {name}: {languages}",
                )
        else:
            return [self.domain_data(d_m) for d_m in domain]

    def post_patch_domain_lang_from_flat(
            self, domain_name: str, language: str, data: List[Tuple[str, str]], actor: RegisteredActor
    ) -> Tuple[Domainmeta_domainlang, bool]:
        """
        todo refactor!
        @param domain_name:
        @param language:
        @param data:
        @param actor: current actor
        @return: DomainLang model and if it changed its active state (false:no change)
        """
        structured_data = table_col2dict(data)
        title = structured_data[TITLE]
        del structured_data[TITLE]

        domain_lang_model = DomainLang(
            title=title,
            language=language,
            content=DomainLangContent.parse_obj(structured_data.get(CONTENT)),
        )
        domain_merge_model = DomainLang.construct(
            _fields_set=None, **domain_lang_model.dict()
        )
        domain_meta = self.crud_read_meta(domain_name)
        domain_merge_model.content = deep_merge(
            domain_lang_model.content.dict(exclude_none=True), domain_meta.content
        )

        default_language_domain_model = self.crud_read_domain(
            domain_name, domain_meta.default_language
        ).to_model(DomainLang)

        domain_merge_model.is_active = check_model_active(
            default_language_domain_model,
            domain_merge_model,
            {TITLE, CONTENT},
            f"{title}/{language}",
        )
        # = self.check_domain_active(default_language_domain_model,
        #                                                        domain_merge_model)
        domain, inserted, active_changed = self.insert_or_update_domain(
            domain_merge_model, domain_meta, True
        )

        self.check_file_update(domain_name, language, domain_lang_model, actor)

        return Domainmeta_domainlang(domain_meta, domain), active_changed

    def get_domain_lang_missing(self, domain_name: str, language: str):
        domain_meta = self.crud_read_meta(domain_name)
        default_language_domain_model = self.crud_read_domain(
            domain_name, domain_meta.default_language
        ).to_model(DomainLang)

        domain_language: DomainLang = self.crud_read_domain(
            domain_name, language
        ).to_model(DomainLang)

        if default_language_domain_model == domain_language:
            return True

        missing = check_model_active(
            default_language_domain_model,
            domain_language,
            keys={TITLE, CONTENT},
            identity=f"{domain_language.title}/{domain_language.language}",
            check_all=True
        )
        return missing

    def get_codes_templates(
            self,
            domain_name: str,
            language: Optional[str] = None,
            actor: RegisteredActor = None,
            add_default_language: bool = True,
            include_draft: bool = True,
    ):
        """
        # todo explain...
        also falls back to default language
        @param domain_name:
        @param language: if omitted uses the default language of the domain
        @param actor:
        @param add_default_language: also result entries in domain-default language
        @param include_draft: including drafts is important for translation
        @return:
        """
        if add_default_language:
            default_lang = self.crud_read_meta(domain_name).default_language
            if language and language != default_lang:
                # add the default lang and make it an array
                languages = [default_lang, language]
            else:
                languages = [default_lang]
        else:
            if not language:
                raise ApplicationException(
                    HTTP_422_UNPROCESSABLE_ENTITY,
                    "EN:code/templates must either have a "
                    "'language' or 'add_default_language' set true",
                )
            languages = [language]
        q = entries_query_builder(
            self.root_sw,
            actor,
            search_query=build(domain_names=[domain_name], languages=languages),
            entrytypes={CODE, TEMPLATE},
            include_draft=include_draft,
        )
        entries = q.all()

        def only_one(slug):
            of_slug = list(filter(lambda e: e.slug == slug, entries))
            if len(of_slug) == 2:
                return next(filter(lambda e: e.language == language, of_slug))
            else:
                return of_slug[0]

        all_slugs = set((e.slug for e in entries))
        return list(only_one(s) for s in all_slugs)

    def check_file_update(
            self, domain_name: str, language: str, model: DomainLang, actor: RegisteredActor
    ):
        jsonfile = self.root_sw.data.get_init_file(
            domain_name, DOMAIN, lang=language, raise_error=False
        )
        if jsonfile.exists() and (actor and actor.is_admin):
            file_data = model.dict(
                exclude_none=True, exclude={LANGUAGE, "domainmeta", IS_ACTIVE}
            )
            jsonfile.write(file_data)

    def set_domainmeta_active(self, domain_name: str, active: bool) -> bool:
        """
        @param domain_name:
        @param active:
        @return: success
        """
        self.crud_read_meta(domain_name).is_active = active
        self.db_session.commit()
        return True

    def filter_fallbacks(
            self, dmeta_dlangs: List[Domainmeta_domainlang], preferred_language: str
    ):
        """
        kickout fallback if preferred language is present
        @param dmeta_dlangs:
        @preferred_language:
        @return:
        """
        result = {}
        for dmeta_dlang in dmeta_dlangs:
            if not (d_name := dmeta_dlang.meta.name) in result:
                result[d_name] = dmeta_dlang
            elif dmeta_dlang.lang.language == preferred_language:
                result[d_name] = dmeta_dlang
        return list(result.values())

    async def rename_source_folder_to_ignore(self, domain_name):
        """
        after deleting a domain, the folder should be renamed starting with "_" so it wont be loaded in the future
        @param domain_name:
        @return:
        """
        orig_dir = os.path.join(INIT_DOMAINS_FOLDER, domain_name)
        if os.path.isdir(orig_dir):
            ignore_dir_name = os.path.join(INIT_DOMAINS_FOLDER, f"_{domain_name}")
            await aiofiles.os.rename(orig_dir, ignore_dir_name)

    def validate_entry_refs(
            self, domain_meta: DomainBase, raise_error: bool = False
    ) -> List[Tuple[Location_validation, str]]:
        """
        checks if referenced entries (by slug) exists in the database in the default language.
        Raises an exception if some required ones are missing
        :param domain_meta:
        :return: Tuple: location_validation_item, the slug of the missing entry
        """

        content_locations = [
            Location_validation("$.search.default_templates", True),
            Location_validation("$.include_entries"),
        ]
        # logger.warning(domain_meta.content)
        domain_content = domain_meta.content.dict()
        missing = []
        for loc_val in content_locations:
            value = jsonpath.jsonpath(domain_content, loc_val.path)
            if value:
                # cuz jsonpath always returns a list
                value = value[0]
                for slug in value:
                    e = self.root_sw.template_codes.get_by_slug_lang(
                        slug, domain_meta.default_language, False
                    )
                    if not e and loc_val.required:
                        if raise_error:
                            raise ApplicationException(
                                HTTP_422_UNPROCESSABLE_ENTITY,
                                f"entry {slug} missing at path:content.{loc_val.path} for domain: "
                                f"{domain_meta.name}",
                            )
                        missing.append((loc_val, slug))
        return missing
