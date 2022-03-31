import csv
import os
import re
import subprocess
from glob import glob
from logging import getLogger
from os.path import join, basename, exists
from fastapi import FastAPI
from sqlalchemy import Column, String, Float, Boolean, Integer, JSON

from app.models.schema.translation_models import UserGuideMappingFormat
from app.services.service_worker import ServiceWorker
from app.settings import (
    env_settings,
    BASE_LANGUAGE_DIR,
    BACKEND_MESSAGE_COMPONENT,
    FRONTEND_MESSAGE_COMPONENT,
    MESSAGES_LANGUAGES,
    MESSAGES_STATUSES,
    MESSAGES_DB_PATH,
    BASE_MESSAGES_DIR,
    MESSAGES_CHANGES, BASE_DIR
)
from app.util.consts import (
    LANGUAGE_TABLE_COLUMNS,
    MESSAGE_TABLE_INDEX_COLUMN,
    LANGUAGE_TABLE_COLUMNS_ALL_CODES,
)
from app.util.dict_rearrange import dict2row_iter
from app.util.files import get_abs_path, CSVPath, JSONPath

logger = getLogger(__name__)


def messages_db_exists() -> bool:
    return exists(MESSAGES_DB_PATH)


def setup_translations(app: FastAPI, sw: ServiceWorker, new_db: bool):
    if new_db:
        logger.info(f"Creating messages db at {MESSAGES_DB_PATH}")

    setup_user_guides_mapping(app)

    if not (env_settings().INIT_LANGUAGE_TABLES or new_db):
        return

    logger.info(
        f"load language tables: {env_settings().INIT_LANGUAGE_TABLES}, new_db: {new_db}"
    )

    try:
        if new_db:
            setup_language_name_source_repo()
            setup_language_names_table(sw)
            setup_status_table(sw)
            setup_changes_table(sw)

            for lang in env_settings().DEACTIVATE_LANGUAGES:
                if sw.messages.has_language(lang):
                    sw.messages.change_lang_status(lang, False)
                else:
                    logger.info(
                        f"environment variable DEACTIVATE_LANGUAGES contains a language that is not added: {lang}"
                    )
        # mostly for dev-environment. take the json file from the frontend project and update the tables
        if (
            env_settings().is_dev
            and env_settings().DEFAULT_LANGUAGE_FE_MESSAGES_FILE
        ):
            update_fe_default_lang_messages()

        setup_messages_db(sw, new_db)

    except Exception as err:
        if new_db:
            os.remove(MESSAGES_DB_PATH)
        if isinstance(err, FileNotFoundError):
            logger.error(f"Language file missing: {err.filename}")
            logger.error("Exiting")
            exit(1)
        logger.exception(err)
        logger.exception("Messages db setup failed")



def update_fe_default_lang_messages():
    """
    Updated the fe.csv from a json file in the an arbitrary json file (in the fe-development repo)
    @return:
    """
    fe_message_file = env_settings().DEFAULT_LANGUAGE_FE_MESSAGES_FILE
    if not fe_message_file:
        return
    fe_messages = JSONPath(fe_message_file).read()
    new_rows = list(dict2row_iter(fe_messages))

    server_file = join(BASE_LANGUAGE_DIR, "fe.csv")

    try:
        server_rows = csv.reader(open(server_file, encoding="utf-8"))
    except Exception as err:
        logger.exception(err)
        exit(1)
    columns = next(server_rows)
    csv_index_map = {}
    for row in server_rows:
        lang_dict = dict(zip(columns, row))
        csv_index_map[lang_dict[MESSAGE_TABLE_INDEX_COLUMN]] = lang_dict

    default_lang = env_settings().DEFAULT_LANGUAGE
    fout = open(server_file, "w", encoding="utf-8")
    writer = csv.DictWriter(fout, fieldnames=columns)
    writer.writeheader()
    for new_default_lang_msg in new_rows:
        index, msg = new_default_lang_msg
        if index in csv_index_map:
            new_row = {**csv_index_map[index], default_lang: msg}
        else:
            new_row = {MESSAGE_TABLE_INDEX_COLUMN: index, default_lang: msg}
        writer.writerow(new_row)
    fout.close()


def setup_language_names_table(sw: ServiceWorker):
    """
    Takes 'languages.csv' from init_data/languages dir and adds all its content
    to the MESSAGES_LANGUAGES table (languages).
    Fails if the file is missing
    Fails if the columns LANGUAGE_TABLE_COLUMNS: ["639-1", "name"]  are missing
    @param sw:
    """
    language_file = join(BASE_LANGUAGE_DIR, "languages.csv")
    languages = CSVPath(get_abs_path(language_file)).read(as_dict=True)

    if missing_cols := list(
        req_col_name
        for req_col_name in LANGUAGE_TABLE_COLUMNS
        if req_col_name not in languages.fieldnames
    ):
        raise ValueError(
            f"file {language_file} is missing some columns: {missing_cols}"
        )

    columns = []
    for field in languages.fieldnames:
        columns.append(
            Column(
                field,
                String,
                index=field == LANGUAGE_TABLE_COLUMNS[0],  # 639-1
                unique=field in LANGUAGE_TABLE_COLUMNS_ALL_CODES,
            )
        )
    sw.messages.create_table("languages", columns)
    sw.messages.add_new_words("languages", [r for r in languages])


def setup_language_name_source_repo():
    """
    runs git to grab the repo LANGUAGE_LIST_SOURCE_REPO_URL "https://github.com/umpirsky/language-list" to
    BASE_LANGUAGE_DIR/"source_repo"
    """
    local_repo_path = join(BASE_LANGUAGE_DIR, f"source_repo")
    if os.path.isdir(local_repo_path):
        return
    try:
        logger.info(
            f"cloning repo: {env_settings().LANGUAGE_LIST_SOURCE_REPO_URL} -> {local_repo_path}"
        )
        subprocess.run(
            [
                "git",
                "clone",
                env_settings().LANGUAGE_LIST_SOURCE_REPO_URL,
                local_repo_path,
            ]
        )
    except Exception as err:
        logger.exception(
            f"Could not clone repo {env_settings().LANGUAGE_LIST_SOURCE_REPO_URL}"
        )
        logger.exception(err)
        raise err


def setup_messages_db(sw: ServiceWorker, new_db: bool):
    """
    Takes be.csv and fe.csv from BASE_MESSAGES_DIR to build/update the messages in the db
    Only considers [BACKEND_MESSAGE_COMPONENT, FRONTEND_MESSAGE_COMPONENT]: (be.csv and fe.csv).
    Both files need to have the MESSAGE_TABLE_INDEX_COLUMN (index_) column first
    Checks if the languages are the same in both files and only takes the union
    Adds all these languages to the system
    Fails if there are no files
    Fails if the first column of any file is not MESSAGE_TABLE_INDEX_COLUMN (index_)
    @param sw:
    @param new_db: set if the db is new
    """

    # TODO, the whole first part could be restructured to just check and grab the 2 component files
    component_files = glob(join(BASE_MESSAGES_DIR, "*.csv"))
    if component_files:
        logger.warning(f"Use of deprecated file locations for message csv files {BASE_MESSAGES_DIR}. "
                       f"Use {BASE_LANGUAGE_DIR}")
    else:
        component_files = [f for f in glob(join(BASE_LANGUAGE_DIR, "*.csv")) if re.search(r'.*(fe|be)\.csv$', f)]

    if not component_files:
        err = FileNotFoundError(
            f"No component files (be.csv, fe.csv) found in  {BASE_MESSAGES_DIR} nor {BASE_LANGUAGE_DIR}")
        err.filename = f"{BASE_LANGUAGE_DIR}/*.csv"
        raise err
    else:
        logger.debug(f"language csvs: {component_files}")

    file_languages = {}
    relevant_files = []
    for file in component_files:
        # todo Use CSVPath
        component_name = basename(file)[:-4].lower()
        if component_name not in [
            BACKEND_MESSAGE_COMPONENT,
            FRONTEND_MESSAGE_COMPONENT,
        ]:
            logger.info(f"unidentified message component. skipping: {component_name}")
            continue
        reader = csv.DictReader(open(file, encoding="utf-8"))
        if not MESSAGE_TABLE_INDEX_COLUMN == reader.fieldnames[0]:
            raise TypeError(
                f"Table has not {MESSAGE_TABLE_INDEX_COLUMN} as first field"
            )

        relevant_files.append(file)
        file_languages[component_name] = [
            lang.lower()
            for lang in reader.fieldnames
            if lang != MESSAGE_TABLE_INDEX_COLUMN and lang
        ]
        logger.debug(
            f"component {component_name} has these languages: {file_languages[component_name]}"
        )

    # Get languages in the files and add new ones
    be_langs = sorted(file_languages[BACKEND_MESSAGE_COMPONENT])
    fe_langs = sorted(file_languages[FRONTEND_MESSAGE_COMPONENT])

    # only take languages which exist in both files (set-languages)
    if be_langs != fe_langs:
        logger.warning(
            f"languages do not match: BE: {file_languages[BACKEND_MESSAGE_COMPONENT]}, "
            f"FE: {file_languages[FRONTEND_MESSAGE_COMPONENT]}"
        )
        languages = set(
            lang
            for lang in set(fe_langs + be_langs)
            if lang in be_langs and lang in fe_langs
        )
    else:
        languages = set(be_langs)

    # if there is no db: ...
    # create a component tables (fe, be) add fill it with the messages of the set-languages
    if new_db:
        for file in relevant_files:
            # create component tables
            component_name = basename(file)[:-4].lower()
            reader = csv.DictReader(open(file, encoding="utf-8"))
            languages = [
                lang.lower()
                for lang in reader.fieldnames
                if lang != MESSAGE_TABLE_INDEX_COLUMN
            ]
            sw.messages.create_component_table(component_name)
        # add languages
        for lang in languages:
            if not sw.messages.has_language(lang):
                sw.messages.add_language(lang, True)
                logger.info(f"Adding language: {lang}")
        # add messages
        for file in relevant_files:
            component_name = basename(file)[:-4].lower()
            reader = csv.DictReader(open(file, encoding="utf-8"))
            sw.messages.add_new_words(component_name, [r for r in reader])
        return

    # add languages, if new ones are there
    for lang in languages:
        if not sw.messages.has_language(lang):
            sw.messages.add_language(lang)
            logger.info(f"Adding language: {lang}")

    for file in relevant_files:
        if not new_db:
            component_name = basename(file)[:-4].lower()
            reader = csv.DictReader(open(file, encoding="utf-8"))

            update_results = sw.messages.safe_update(
                component_name,
                [r for r in reader],
                replace_messages=env_settings().REPLACE_MESSAGES,
            )

            logger.info(
                f"messages.safe_update: {component_name}: Missing: {update_results['added']}; "
                f"Changes: {update_results['changes']}; Removed: {update_results['removed']}; "
                f"Insertions: {update_results['inserted']}"
            )


def check_messages_db(sw: ServiceWorker) -> bool:
    # todo can we just access the db_conn directly?
    existing_tables = sw.messages.message_db_conn.tables
    all_tables = [
        BACKEND_MESSAGE_COMPONENT,
        FRONTEND_MESSAGE_COMPONENT,
        MESSAGES_LANGUAGES,
        MESSAGES_STATUSES,
    ]
    if any(filter(lambda table: table not in existing_tables, all_tables)):
        return False
    return True


def setup_status_table(sw: ServiceWorker):
    columns = [
        Column("lang_code", String, nullable=False, index=True, unique=True),
        Column("active", Boolean, nullable=False, default=False),
        Column("fe_msg_count", Integer, nullable=False),
        Column("be_msg_count", Integer, nullable=False),
        Column("fe_outdated", JSON, default={}),  # docs="dict: index:bool:validated?"
        Column("be_outdated", JSON, default={}),
    ]  #
    sw.messages.create_table(MESSAGES_STATUSES, columns)


def setup_changes_table(sw: ServiceWorker):
    columns = [
        Column("index", Integer, primary_key=True, nullable=False, autoincrement=True),
        Column("lang_code", String, nullable=False),
        Column("timestamp", Float, nullable=False),
        Column("registered_name", String, nullable=False),
        Column("component", String, nullable=False),
        Column(MESSAGE_TABLE_INDEX_COLUMN, String, nullable=False),
        Column("prev_msg", String, nullable=True),
    ]
    sw.messages.create_table(MESSAGES_CHANGES, columns)


def setup_user_guides_mapping(app: FastAPI):
    """
    A UserGuideMappingFormat object which is added to the app.state, which includes the mappings from
    lang_code -> lang_code, and lang_code -> url, where the user-guides are. for user-guides in different languages
    @param app: the fastapi app
    """
    path = join(BASE_LANGUAGE_DIR, "user_guides_mapping.json")
    user_guides_mapping_file = JSONPath(path, raise_error=False)
    if user_guides_mapping_file.exists():
        try:
            app.state.user_guides_mapping = UserGuideMappingFormat.parse_obj(
                user_guides_mapping_file.read()
            )
        except (JSONDecodeError, ValidationError) as err:
            logger.error(f"Failed to parse user_guides_mapping.json: {err}")
    else:
        logger.info(f"No user_guides_mapping.json found at {user_guides_mapping_file.relative_to(BASE_DIR)}. "
                    f"Creating it with empty values")
        user_guides_mapping_file.write(UserGuideMappingFormat(pages={}, mapping={}).dict())

