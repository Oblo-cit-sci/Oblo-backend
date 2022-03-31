import os
import shutil
from glob import glob
from logging import getLogger
from os.path import join, basename, isdir, isfile
from typing import Dict, List

import dirsync
from deepmerge.exception import InvalidMerge
from deprecated.classic import deprecated
from orjson import JSONDecodeError
from pydantic import ValidationError
from sqlalchemy.exc import DatabaseError, StatementError

from app import settings
from app.models.orm import RegisteredActor, Domain
from app.models.schema.domain_models import DomainLang, DomainBase
from app.services import schemas
from app.services.schemas import domain_data_schema_file
from app.services.service_worker import ServiceWorker
from app.settings import env_settings, INIT_DOMAINS_FOLDER
from app.setup.init_data.init_entries import init_entries
from app.setup.init_data.plugin_import import init_plugin_import
from app.util.consts import NO_DOMAIN, NAME, DEFAULT_LANGUAGE, LANGUAGE, TITLE, CONTENT
from app.util.dict_rearrange import deep_merge, check_model_active
from app.util.files import read_orjson, JSONPath
from app.util.language import get_language_code_from_domain_path

logger = getLogger(__name__)


def get_domain_folder(domain_name: str):
    return join(INIT_DOMAINS_FOLDER, domain_name)


def get_domain_lang_folder(domain_name: str, language: str):
    return join(INIT_DOMAINS_FOLDER, domain_name, language)


def get_domain_lang_type_folder(domain_name, language, type_name: str):
    return join(INIT_DOMAINS_FOLDER, domain_name, language, type_name)


def init_domains(sw: ServiceWorker, actor: RegisteredActor):
    """
    loads all init-data from all domains specified in the settings: LOAD_DOMAINS or
    (if empty) given in the INIT_DOMAINS_FOLDER folder
    @param sw: service
    @param actor: the actor assigned as creator (normally admin)
    """
    logger.debug("*** Domains")

    # todo should also be used to kick out domains again
    domain_folders = glob(INIT_DOMAINS_FOLDER + "/*")
    domain_folders = list(filter(lambda f: os.path.isdir(f), domain_folders))
    domains_to_load = [basename(d) for d in domain_folders]
    domains_to_load = list(
        filter(lambda name: not name.startswith("_"), domains_to_load)
    )

    if not domain_folders:
        logger.error(
            f"No domain folders found in {INIT_DOMAINS_FOLDER}. You need to include at least 'no_domain"
        )
        return

    # load no_domain first for codes, templates...
    if NO_DOMAIN in domains_to_load:
        domains_to_load.remove(NO_DOMAIN)
        domains_to_load = [NO_DOMAIN] + domains_to_load
    logger.info(f"domains to load:{domains_to_load}")

    for domain_name in domains_to_load:
        init_domain(domain_name, sw, actor)


def init_domain(domain_name: str, sw: ServiceWorker, actor: RegisteredActor):
    """
    Initialize one domain: domain-meta, domain (in languages) and its entries
    @param domain_name: name of the domain (looking for data in the corresponding folder)
    @param sw: service
    @param actor: actor as creator for all the entries
    """
    logger.debug(f"Domain: {domain_name}")
    domain_base_folder = join(INIT_DOMAINS_FOLDER, domain_name)

    update_domain_images(domain_name)

    init_plugin_import(domain_name)
    update_domain_js_plugin(domain_name)

    # read, validate and insert domainmeta
    domain_base_file_path = join(domain_base_folder, "domain.json")
    try:
        meta_file = JSONPath(domain_base_file_path)
        meta_data = meta_file.read_insert(
            insert={NAME: domain_name},
            setdefault={DEFAULT_LANGUAGE: env_settings().DEFAULT_LANGUAGE},
        )
        meta_model = DomainBase.parse_obj(meta_data)
        meta_object = sw.domain.insert_or_update_meta(meta_model)
    except (FileNotFoundError, ValueError, JSONDecodeError, ValidationError) as err:
        logger.error(err)
        logger.error(f"Skipping domain: {domain_name}")
        return

    # return if not active
    if not meta_object.is_active:
        logger.info(f"Domain {domain_name} is not active. Not loading language files")
        return

    # get all language files...
    lang_domain_files = [
        JSONPath(_) for _ in glob(domain_base_folder + "/lang/*/domain.json")
    ]

    if len(lang_domain_files) == 0:
        logger.warning(f"Domain in no language: {domain_name}")

    # put the language file which has the language defined as default_language first
    # this will be set to active and all other need to include (at least) those
    # text fields (text, label, description, ...)
    # in their aspects & items...
    default_lang_file_found = False
    for (index, f) in enumerate(lang_domain_files):
        if f.parent.name == meta_model.default_language:
            lang_domain_files[0], lang_domain_files[index] = (
                lang_domain_files[index],
                lang_domain_files[0],
            )
            default_lang_file_found = True
            break
    if not default_lang_file_found:
        logger.error(
            f"No domain language file found for the domain: {meta_model.name}. Not doing anything with this domain"
        )
        return

    default_language_domain_model = None
    # read, validate, merge (with meta)  and insert domain-lang objects
    for lang_domain_file in lang_domain_files:
        language = basename(lang_domain_file.parent)
        l_msg_name = f"{domain_name}/{language}"
        logger.debug(f"Domain ({l_msg_name})")
        try:
            domain_lang_data = lang_domain_file.read_insert(
                insert={"language": language}
            )
            domain_lang_model = DomainLang.parse_obj(domain_lang_data)

            domain_lang_model.content = deep_merge(
                domain_lang_model.content.dict(exclude_none=True),
                meta_model.content.dict(exclude_none=True),
                True,
            )

            if language == meta_model.default_language:
                domain_lang_model.is_active = True
                default_language_domain_model = domain_lang_model
            else:
                title = domain_lang_model.title
                lang = domain_lang_model.language
                domain_lang_model.is_active = check_model_active(
                    default_language_domain_model,
                    domain_lang_model,
                    {"title", "content"},
                    f"{title}/{lang}",
                    False,
                    True,
                )
            sw.domain.insert_or_update_domain(domain_lang_model, meta_object)
            if not sw.messages.has_language(language):
                sw.messages.add_language(language)

        except (
            FileNotFoundError,
            ValueError,
            JSONDecodeError,
            ValidationError,
            InvalidMerge,
        ) as err:
            logger.exception(err)
            logger.error(f"Skipping domain: {l_msg_name}")
            if language == meta_model.default_language:
                logger.error(f"Skipping all other languages...")
                break

    # update database objects that have no files
    dlang_objects: List[Domain] = meta_object.language_domain_data
    lang_file_languages = [basename(file.parent) for file in lang_domain_files]
    for db_obj in dlang_objects:
        if db_obj.language not in lang_file_languages:
            ident = f"{domain_name}: {db_obj.language}"
            logger.info(f"Updating database domain object: {ident}")

            try:
                domain_lang_model = DomainLang.parse_obj(
                    {**DomainLang.from_orm(db_obj).dict(), LANGUAGE: db_obj.language}
                )
                domain_lang_model.content = deep_merge(
                    domain_lang_model.content.dict(exclude_none=True),
                    meta_model.content.dict(exclude_none=True),
                    True,
                )
                domain_lang_model.is_active = check_model_active(
                    default_language_domain_model,
                    domain_lang_model,
                    {TITLE, CONTENT},
                    f"{db_obj.title}/{db_obj.language}",
                    False,
                    True,
                )
                sw.domain.insert_or_update_domain(domain_lang_model, meta_object)
            except (ValidationError, InvalidMerge) as err:
                logger.warning(
                    f"Could not merge database language domain entry: {ident}"
                )
                db_obj.is_active = False
                logger.warning(err)

    try:
        sw.db_session.commit()
    except (StatementError, DatabaseError) as err:
        logger.exception(err)
        logger.error(f"Insertion failed for all rows of domain: {domain_name}")

        sw.db_session.rollback()

    sw.data.sync_domain_assets(domain_name)
    if env_settings().INIT_TEMPLATES_CODES:
        init_entries(meta_object, sw, actor)
    missing_entries = sw.domain.validate_entry_refs(meta_model)
    if missing_entries:
        meta_object.is_active = False
        sw.db_session.commit()
        logger.warning(
            f"Some entries are missing...: {missing_entries} deactivating domain"
        )


def update_domain_images(domain_name: str):
    src_path = join(INIT_DOMAINS_FOLDER, domain_name)
    dest_path = join(settings.DOMAINS_IMAGE_FOLDER, domain_name)
    files = ["banner.jpg", "icon.png"]
    for file in files:
        file_path = join(src_path, file)
        if not isfile(file_path):
            if domain_name == NO_DOMAIN:
                raise FileNotFoundError(f"NO_DOMAIN must have image {file}")
            logger.warning(f"Missing {file} for {domain_name}. copying from NO_DOMAIN")
            shutil.copy(join(INIT_DOMAINS_FOLDER, NO_DOMAIN, file), file_path)
    try:
        dirsync.sync(
            src_path,
            dest_path,
            "sync",
            **{
                "create": True,
                "only": files,
                "logger": logger,
            },
        )
    except ValueError as err:
        logger.error(f"Skipping domain-images for {domain_name}")
        logger.exception(err)


def update_domain_js_plugin(domain_name: str):
    src_path = join(INIT_DOMAINS_FOLDER, domain_name, "plugins")
    if not isfile(join(src_path, domain_name + ".js")):
        return
    dest_path = join(settings.JS_PLUGIN_FOLDER)
    if not isdir(dest_path):
        os.makedirs(dest_path)
    try:
        dirsync.sync(
            src_path,
            dest_path,
            "sync",
            **{
                "create": True,
                "only": [domain_name + ".js"],
                "logger": logger,
            },
        )

    except ValueError as err:
        logger.error(f"Skipping domain-images for {domain_name}")
        logger.exception(err)


@deprecated
def read_domain_data(domain_folder: str) -> Dict:
    """
    Reads the domain-data from the domain.json files for all languages
    """
    files = glob(domain_folder + "/lang/*/domain.json")
    domain_translations = {}
    for file in files:
        lang_code = get_language_code_from_domain_path(file)
        lang_domain_data = read_orjson(file)
        try:
            schemas.validate(domain_data_schema_file, lang_domain_data)
            domain_translations[lang_code] = lang_domain_data
        except ValidationError as exc:
            logger.exception(exc)  # exc.path
            logger.warning(
                f"Domain data for domain: {domain_folder}, language: {lang_code} is not valid and will be ignored"
            )
    return domain_translations
