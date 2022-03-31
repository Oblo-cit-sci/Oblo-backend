from datetime import datetime
from logging import getLogger
from time import time
from typing import Optional, Tuple, List, Dict, Union, Sequence, Any

from sqlalchemy import (
    Table,
    select,
    String,
    Column,
    bindparam,
    text,
    MetaData,
    create_engine,
    desc,
)
from sqlalchemy.engine import LegacyRow
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY, HTTP_404_NOT_FOUND

from app.models.schema.translation_models import ContractedMessageBlock
from app.services.service_worker import ServiceWorker
from app.settings import (
    env_settings,
    L_MESSAGE_COMPONENT,
    BACKEND_MESSAGE_COMPONENT,
    FRONTEND_MESSAGE_COMPONENT,
    MESSAGES_STATUSES,
    MESSAGES_CHANGES,
    MESSAGES_LANGUAGES,
    MESSAGES_DB_PATH,
)
from app.util.consts import (
    MESSAGE_TABLE_INDEX_COLUMN,
    VISITOR,
    LANGUAGE_TABLE_COLUMNS,
)
from app.util.exceptions import ApplicationException
from app.util.language import table_col2dict

logger = getLogger(__name__)

tables = {}

"""
TODO check if we need both reflect and reflect_component
"""


class MessageDBConnection:
    db_path: str
    engine = None
    metadata: MetaData
    tables: dict

    def __init__(self):
        """
        initialize db engine and tables
        """
        self.db_path = MESSAGES_DB_PATH
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self.metadata = MetaData(bind=self.engine)
        self.reflect()
        self.tables = dict(self.metadata.tables)

    def reflect(self):
        """
        call reflect in order to update the tables
        """
        self.metadata.reflect()
        self.tables = dict(self.metadata.tables)

    def reflect_components(self):
        self.metadata = MetaData(bind=self.engine)
        self.reflect()
        # todo did not delete columns
        # self.metadata.reflect(only=[BACKEND_MESSAGE_COMPONENT, FRONTEND_MESSAGE_COMPONENT],
        #                       extend_existing=extend_existing)
        self.tables = dict(self.metadata.tables)


message_db_conn = MessageDBConnection()


class MessagesService:
    def __init__(
            self, root_sw: ServiceWorker, default_language: Optional[str], options
    ):
        global message_db_conn
        self.root_sw = root_sw
        self.con = None
        self.cur = None

        self.default_language = MessagesService.lang_arg(default_language)
        self.message_db_conn: MessageDBConnection = message_db_conn
        if not self.default_language:
            self.default_language = options.get(
                "language", env_settings().DEFAULT_LANGUAGE
            )

    def reflect_components(self):
        """
        get the current database through reflection
        """
        self.message_db_conn.reflect_components()

    @classmethod
    def lang_arg(cls, accept_language: Optional[str]) -> Optional[str]:
        """
        check if the language is valid and exists
        """
        # todo check if the language exists in the system
        if accept_language:
            if len(accept_language) == 2:
                return accept_language.lower()
        return env_settings().DEFAULT_LANGUAGE

    def load_table(self, table_name: str, raise_error: bool = True) -> Table:
        """
        load a table through reflection. called when trying to get a table that is not stored yet.
        probably deprecated, since all tables are loaded in the beginning
        @param table_name:
        @param raise_error:
        @return:
        """
        try:
            return Table(
                table_name,
                self.message_db_conn.metadata,
                autoload=True,
                autoload_with=self.message_db_conn.engine,
            )
        except NoSuchTableError as err:
            if raise_error:
                logger.error(f"No such table: {table_name}")
                raise err
            else:
                logger.info(f"Table does not exist {table_name}")

    def has_table(self, table_name: str):
        """
        check if a table exists
        """
        return table_name in self.message_db_conn.tables

    def get_table(self, table_name: str) -> Table:
        """
        get a table either from whats already loaded or loading it
        loading it should maybe go out
        @param table_name:
        @return:
        """
        table = self.message_db_conn.tables.get(table_name)
        if table is None:
            raise ValueError(
                f"Table does not exist: '{table_name}'. Existing tables: {self.message_db_conn.tables}"
            )
        return table

    def execute(self, cmd, args: Any = None):
        """
        execute a command on the db connection
        """
        if args:
            return self.message_db_conn.engine.connect().execute(cmd, args)
        else:
            return self.message_db_conn.engine.connect().execute(cmd)

    def get_component_language_filter(
            self, languages: Optional[List[str]] = None, raise_error: bool = True
    ):
        """
        todo: rename to filter_existing_languages
        Preparation call for get_component. filters existing languages
        @param languages: all languages to check (filter)
        @param raise_error: raise error, when there is no valid language in the list
        @return: list of existing languages
        """
        if languages:
            query_languages = []
            for lang in languages:
                # todo fix validation based on existing languages
                if lang in []:
                    logger.warning(f"language: {lang} does not exist")
                else:
                    query_languages.append(lang)
            if not query_languages and raise_error:  # not in, ..... accepted_langs:
                raise ApplicationException(HTTP_404_NOT_FOUND, "no language is valid")
        else:
            query_languages = self.get_added_languages()
        return query_languages

    def get_component(
            self,
            component: L_MESSAGE_COMPONENT,
            lang_codes: Union[str, List[str], None] = None,
    ) -> List[List[str]]:
        """
        for the ui, get from a table, the index and a number of columns (languages)
        @param component: component
        @param lang_codes: several languages
        @return: a list[rows=messages] of list[index and n. messages].
        """
        table: Table = self.get_table(component)

        if lang_codes:
            if not isinstance(lang_codes, list):
                lang_codes = [lang_codes]
            msgs: List = self.execute(
                select(
                    [
                        table.columns[MESSAGE_TABLE_INDEX_COLUMN],
                        *[table.columns[lang_code] for lang_code in lang_codes],
                    ]
                )
            ).fetchall()
        else:
            msgs: List = self.execute(select(table.columns)).fetchall()
        msgs: List[List[str]] = [list(r) for r in msgs]
        return msgs

    # noinspection PyMethodMayBeStatic
    def component_index_dict(
            self, languages: Sequence[str], component_rows: Sequence[Sequence[str]]
    ) -> Dict[str, Dict[str, str]]:
        """
        turns the results of get_component into a dict: (key: <index>, (value (dict): key: lang_code value: message)
        @param languages:
        @param component_rows:
        @return:
        """
        return {
            row[0]: {languages[index]: col for index, col in enumerate(row[1:])}
            for row in component_rows
        }

    def get_added_languages(self):
        return [lang["lang_code"] for lang in self.get_all_statuses()]

    # todo maybe translation service
    def has_language(self, language_code: str):
        return language_code in self.get_added_languages()

    # noinspection PyMethodMayBeStatic
    def structure_messages(
            self, lang_codes: List[str], messages: List[List[str]]
    ) -> Dict[str, dict]:
        """
        structure the messages into a json object. my notation is just based on ".". also for list indices.
        uses: app/util/language.py

        @param lang_codes: language codes of the messages
        @param messages: a list of list. (as it comes from get_component)
        @return: a dict, where the keys are the language codes and the values the structured messages
        """
        result = {}
        for index, lang in enumerate(lang_codes):
            l_msgs = [(msg_tuple[0], msg_tuple[index + 1]) for msg_tuple in messages]
            result[lang] = table_col2dict(l_msgs)
        return result

    def t(
            self,
            index: str,
            language: Optional[str] = None,
            component: Optional[str] = BACKEND_MESSAGE_COMPONENT,
    ):
        """
        translate a message
        @param index: index of the message
        @param language: default language is server default language
        @param component: default component is "be"
        @return: a message string
        """
        language = language if language else self.default_language
        table = self.get_table(component)
        result = self.execute(
            select(
                [
                    table.columns[language],
                    table.columns[env_settings().DEFAULT_LANGUAGE],
                ]
            ).where(table.columns[MESSAGE_TABLE_INDEX_COLUMN] == index)
        ).fetchone()
        # logger.warning("!!!", result)
        # results = self.execute(
        #     select([be_table.columns[language]]).where(be_table.columns["index_"] == index)).fetchone()
        if not result:
            logger.exception(f"Wrong index ({index}) for table: {component}")
            return ""
        if result[0]:  # requested language
            return result[0]
        else:  # default server language
            return result[1]

    def t_list(
            self,
            indices: List[str],
            language_code: Optional[str] = None,
            component: Optional[str] = BACKEND_MESSAGE_COMPONENT,
    ) -> Dict[str, Tuple[str, str]]:
        """
        gets the translation of a list of words. includes the default language if missing
        @param indices:
        @param language_code:
        @param component:
        @return: a tuple of language_code and message
        """
        table = self.get_table(component)
        default_language = env_settings().DEFAULT_LANGUAGE
        rows = self.execute(
            select(
                [
                    table.columns[MESSAGE_TABLE_INDEX_COLUMN],
                    table.columns[language_code],
                    table.columns[default_language],
                ]
            ).where(table.columns[MESSAGE_TABLE_INDEX_COLUMN].in_(indices))
        ).fetchall()
        return {
            row[0]: ((language_code, row[1]) if row[1] else (default_language, row[2]))
            for row in rows
        }

    def get_missing_words(
            self, component: str, language: str, source_languages: List[Dict[str, str]] = ()
    ) -> List[Dict[str, str]]:
        """
        @param component:
        @param language:
        @param source_languages:
        @return:
        """
        table = self.get_table(component)
        columns = [MESSAGE_TABLE_INDEX_COLUMN] + source_languages
        rows: List[LegacyRow] = self.execute(
            select([table.columns[col] for col in columns]).where(
                table.columns[language].is_(None)
            )
        ).fetchall()
        # private because  sql-alchemy wants it that way instead of row.items()
        # also, cannot just use values(would need zipping with the columns
        # must convert keys to strings cuz the are of some sqlalchemy type
        return [{str(key): value for (key, value) in row._mapping.items()} for row in rows]

    def create_table(self, name, columns: List[Column]):
        table = Table(name, self.message_db_conn.metadata)
        for col in columns:
            table.append_column(col)
        self.message_db_conn.metadata.create_all(
            self.message_db_conn.engine, [table], checkfirst=True
        )
        self.message_db_conn.tables[name] = table
        return table

    def create_component_table(self, component: L_MESSAGE_COMPONENT):
        """
        creates a new table
        @param component:
        @return:
        """
        logger.debug(f"creating component table: {component}")
        columns = [
            Column(MESSAGE_TABLE_INDEX_COLUMN, String, unique=True, primary_key=True)
        ]
        self.create_table(component, columns)

    def add_new_word(
            self,
            component: L_MESSAGE_COMPONENT,
            index: str,
            translations: Dict[str, str],
            raise_error: bool = True,
    ):
        """
        @param component:
        @param index
        @param translations
        @param raise_error:
        """
        table = self.get_table(component)
        for language in translations.keys():
            if language not in table.columns:
                raise ApplicationException(
                    HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{language} is not a language",
                    data={"language": [language]},
                )
        try:
            self.execute(
                table.insert().values(
                    {**{MESSAGE_TABLE_INDEX_COLUMN: index}, **translations}
                )
            )
            logger.info(f"new word added to: {component}: {index}: {translations}")
        except IntegrityError:
            if raise_error:
                raise ApplicationException(
                    HTTP_422_UNPROCESSABLE_ENTITY,
                    f"index does already exist: {component} / {index}",
                )
            else:
                logger.warning(f"Duplicate index will be ignored {component} / {index}")

    def add_new_words(
            self, component: L_MESSAGE_COMPONENT, messages: List[Dict[str, Optional[str]]]
    ):
        """
        @param component:
        @param messages: list of messages, dict for language: word, should also include MESSAGE_TABLE_INDEX_COLUMN
        @return:
        """
        stmt = self.get_table(component).insert()
        # dont insert empty strings. they will not be replaced in the ui
        for m in messages:
            for k, v in m.items():
                if not v:
                    m[k] = None
        # todo: use internal execute
        self.message_db_conn.engine.connect().execute(stmt, messages)

    def safe_update(
            self,
            component: L_MESSAGE_COMPONENT,
            messages: List[Dict[str, Optional[str]]],
            remove_unused: bool = True,
            replace_messages: bool = True,
    ):
        """
        run through the messages, and fill in what is missing. return what is different in the db (dont update)
        delete rows that are not in the list
        @param component:
        @param messages:
        @param remove_unused: remove from db, which dont exist in the passed messages list
        @param replace_messages: replace in db, when they differ
        @return:
        """
        messages_index_map = {m[MESSAGE_TABLE_INDEX_COLUMN]: m for m in messages}
        languages = list(
            filter(lambda i: i != MESSAGE_TABLE_INDEX_COLUMN and i, messages[0].keys())
        )
        db_index_map = self.component_index_dict(
            languages, self.get_component(component, languages)
        )
        missing_in_db: List[Dict[str, str]] = []
        changes = {}  # key: index, value: dict(lang-code: prev-message)
        removed = list(db_index_map.keys())  # in the db but not in the csv
        inserted = {}

        for index, messages in messages_index_map.items():
            db_messages = db_index_map.get(index)
            # insert into db if it doesnt exist
            if not db_messages:
                missing_in_db.append(messages_index_map[index])
            else:
                removed.remove(index)
                # if it exists go through all languages
                for lang_code, msg in messages.items():
                    # todo: remove index before...
                    if lang_code == MESSAGE_TABLE_INDEX_COLUMN:
                        continue
                    # dont fill in empty strings into the db
                    if msg == "":
                        msg = None
                    db_msg = db_messages.get(lang_code)
                    # compare csv msg with db msg
                    if msg != db_msg:
                        if msg and not db_msg:  # csv has text but db has None: insert
                            inserted.setdefault(index, {})[lang_code] = msg
                        else:
                            changes.setdefault(index, {})[lang_code] = [db_msg, msg]
                            # if replace_messages:
                            #     inserted.setdefault(index, {})[lang_code] = msg

        removed = list(filter(lambda index_: not index_.startswith("lang."), removed))
        if remove_unused:
            self.remove_words(component, removed)

        if missing_in_db:  # needs a check, or inserts empty row
            logger.info(
                f"Safe-update adding words from csv of component: {component}, words: {missing_in_db}"
            )
            self.add_new_words(component, missing_in_db)

        if inserted:
            # for now using update_messages, which only does one language at a time
            # so need to transform it.
            # todo but same structure as adding:
            #  [{MESSAGE_TABLE_INDEX_COLUMN: index, **word_dict} for index, word_dict in inserted.items()]
            # would be nice...
            language_grouped = {}

            for index, messages in inserted.items():
                for lang_code, word in messages.items():
                    language_grouped.setdefault(lang_code, []).append((index, word))
            for lang_code, messages in language_grouped.items():
                self.update_component_for_one_language(component, lang_code, messages)

        if replace_messages and changes:
            language_grouped = {}
            for index, messages in changes.items():
                for lang_code, word_change in messages.items():
                    language_grouped.setdefault(lang_code, []).append(
                        (index, word_change[1])
                    )
            for lang_code, messages in language_grouped.items():
                self.update_component_for_one_language(component, lang_code, messages)

        logger.info(
            f"messages.safe_update: {component}: Missing: {missing_in_db}; "
            f"Changes: {changes}; Removed: {removed}; Insertions: {inserted}"
        )

        return {
            "removed": removed,
            "added": missing_in_db,
            "changes": changes,
            "inserted": inserted,
        }

    def add_translations_for_component(
            self,
            component: L_MESSAGE_COMPONENT,
            translations: List[ContractedMessageBlock],
    ):
        """
        list of indexed messages in various languages
        """
        for translation in translations:
            try:
                self.add_new_word(
                    component, translation.index, translation.translations
                )
            except ApplicationException as err:
                raise err

    def update_component_for_one_language(
            self,
            component: L_MESSAGE_COMPONENT,
            language: str,
            messages: List[Tuple[str, str]]
    ):
        """
        name of this and add_translations dont really make clear what they do
        """
        table = self.get_table(component)
        # when service worker is passed (for posts) we capture the previous message and log it

        indices = [m[0] for m in messages]
        prev = self.execute(
            select(
                [table.columns[MESSAGE_TABLE_INDEX_COLUMN], table.columns[language]]
            ).where(table.columns[MESSAGE_TABLE_INDEX_COLUMN].in_(indices))
        ).fetchall()
        if len(prev) != len(messages):
            logger.warning(
                f"Less existing rows than passed..., {len(prev)}, {len(messages)}"
            )
            prev_indices = set(tu[0] for tu in prev)
            logger.warning([index for index in indices if index not in prev_indices])
        changes_table = self.get_table(MESSAGES_CHANGES)
        timestamp = time()
        # shouldn't be grabbed here but passed as param
        registered_name = VISITOR
        if self.root_sw.request:
            try:
                registered_name = (
                    self.root_sw.request.state.current_actor.registered_name
                )
            except AttributeError as err:
                logger.warning(
                    f"No current_actor in the request.state, this should be avoided by having "
                    f"the route with a right Dependency. Setting to 'visitor'"
                    f"{err}"
                )
        change_stmt = changes_table.insert().values(
            [
                {
                    "lang_code": language,
                    "timestamp": timestamp,
                    "registered_name": registered_name,
                    "component": component,
                    MESSAGE_TABLE_INDEX_COLUMN: msg[0],
                    "prev_msg": msg[1],
                }
                for msg in prev
            ]
        )
        self.execute(change_stmt)

        stmt = (
            table.update()
                .where(table.columns[MESSAGE_TABLE_INDEX_COLUMN] == bindparam("index"))
                .values(**{language: bindparam("message")})
        )
        self.execute(stmt, [{"index": m[0], "message": m[1]} for m in messages])

        # if it is the default language-we chek all other languages (and set them to outdated)!
        if language == env_settings().DEFAULT_LANGUAGE:
            status_table = self.get_table(MESSAGES_STATUSES)
            changed_messages = self.execute(
                select(table.columns).where(
                    table.columns[MESSAGE_TABLE_INDEX_COLUMN].in_(indices)
                )
            ).fetchall()
            language_grouped = {}
            for messages in changed_messages:
                lang_msg_dict = {
                    c.name: messages[index]
                    # todo try table.columns.values()
                    for (index, c) in enumerate(table.columns)
                    if c.name not in [MESSAGE_TABLE_INDEX_COLUMN, language]
                }
                index = messages["index_"]
                outdated_lang = [lang for lang, msg in lang_msg_dict.items() if msg]
                for lang in outdated_lang:
                    language_grouped.setdefault(lang, []).append(index)
                # stmt = status_table.update().where(status_table.columns[])

            column = f"{component}_outdated"  # fe_outdated or be_outdated
            languages = list(language_grouped.keys())

            if languages:
                outdated_in_db = self.execute(
                    select([status_table.columns[column]]).where(
                        status_table.columns["lang_code"].in_(languages)
                    )
                ).fetchall()
                new_values = []
                logger.warning(f"{languages}")

                for lang, in_db in zip(languages, outdated_in_db):
                    in_db = in_db[0]  # since its its a tuple...
                    new_outdated = {i: False for i in language_grouped[lang]}
                    if not in_db:
                        new_val = new_outdated
                    else:
                        new_val = {**in_db, **new_outdated}
                    new_values.append({"lang": lang, "new_outdated": new_val})

                outdated_stmt = (
                    status_table.update()
                        .where(status_table.columns["lang_code"] == bindparam("lang"))
                        .values(**{column: bindparam("new_outdated")})
                )
                logger.warning(new_values)
                self.execute(outdated_stmt, new_values)

    def bulk_update(
            self, component: L_MESSAGE_COMPONENT, messages: List[Dict[str, Optional[str]]]
    ):
        """
        todo: pretty much as add_translations_for_component
        """
        # that a tricky one. but would be needed in safe-update
        table = self.get_table(component)
        stmt = (
            self.get_table(component)
                .update()
                .where(table.columns[MESSAGE_TABLE_INDEX_COLUMN] == bindparam("index"))
        )
        # dont insert empty strings. they will not be replaced in the ui
        for m in messages:
            for k, v in m.items():
                if not v:
                    m[k] = None
        table = self.get_table(component)
        self.execute(table.delete())

    def search_language(self, search_q: str):
        # todo, doesnt take the columns param...
        table = self.get_table(MESSAGES_LANGUAGES)
        select_e = select([table.columns[c] for c in LANGUAGE_TABLE_COLUMNS])
        stmt = select_e.where(text("languages.name LIKE :sq"))
        return (
            self.message_db_conn.engine.connect()
                .execute(stmt, sq="%" + search_q + "%")
                .fetchall()
        )

    def add_language(self, language_code, active: bool = False):
        """
        Add a new language to the system.
        Fails if the language is not in the used code-list
        Fails if the language exists already
        @param language_code:
        @param active:
        @return:
        """
        lang_table = self.get_table(MESSAGES_LANGUAGES)
        # todo, dont hard-code 639-1
        exists = self.execute(
            lang_table.select().where(lang_table.columns["639-1"] == language_code)
        ).fetchall()
        # this is crucial atm since column_name is injected into teh textual query
        if not exists:
            ApplicationException(422, f"Unknown language: {language_code}")
        be_table = self.get_table(BACKEND_MESSAGE_COMPONENT)
        if language_code in be_table.columns:
            raise ApplicationException(
                422,
                f"language exists already: {language_code}",
                data={"lang_code": language_code},
            )
        # todo: call internal execute method
        self.message_db_conn.engine.connect().execute(
            text(
                f"ALTER table {BACKEND_MESSAGE_COMPONENT} ADD COLUMN {language_code} varchar"
            )
        )
        self.message_db_conn.engine.connect().execute(
            text(
                f"ALTER table {FRONTEND_MESSAGE_COMPONENT} ADD COLUMN {language_code} varchar"
            )
        )
        try:
            self.reflect_components()
            # now the new column is there. we need to add the word(title) for that language
            self.update_messages_for_languages(language_code)
        except Exception as err:
            logger.error("Couldn't add language. reversing")
            logger.error(err)
            # todo call internal execute method
            self.message_db_conn.engine.connect().execute(
                text(
                    f"ALTER table {BACKEND_MESSAGE_COMPONENT} DROP COLUMN {language_code}"
                )
            )
            self.message_db_conn.engine.connect().execute(
                text(
                    f"ALTER table {FRONTEND_MESSAGE_COMPONENT} DROP COLUMN {language_code}"
                )
            )
            self.reflect_components()

        # todo also remove word from FE, for new language

        # after the tables are updated (with reflect) we can update the status table
        self.update_language_status(language_code, active)

    def update_messages_for_languages(
            self, language_code: str, display_warning: bool = True
    ):
        all_languages = [language_code] + self.get_added_languages()
        # get the name of the new language in all languages and add a row with that data
        langs_with_source_files = list(
            filter(
                self.root_sw.translation.languagenamne_sourcefile_exists, all_languages
            )
        )
        if display_warning:  # not needed during setup
            for lang in all_languages:
                if lang not in langs_with_source_files:
                    logger.warning(f"No language names sourcefile for language {lang}")

        # get the name of the new language in all existing (and source-file-available languages and insert it into
        # a new row in the fe table
        messages = self.root_sw.translation.get_one_language_name_in_many_languages(
            language_code, langs_with_source_files
        )
        self.add_new_word(
            FRONTEND_MESSAGE_COMPONENT, f"lang.{language_code}", messages, False
        )

        if language_code in langs_with_source_files:
            language_names = (
                self.root_sw.translation.get_language_names_in_one_language(
                    language_code, langs_with_source_files
                )
            )
            language_messages = [
                (f"lang.{lc}", language_names.get(lc)) for lc in all_languages
            ]
            self.update_component_for_one_language(
                FRONTEND_MESSAGE_COMPONENT, language_code, language_messages
            )
        else:
            logger.warning(
                f"Language has no language-names source file: '{language_code}'. No names of other languages"
            )

    def get_language_names(self, lang_code) -> Dict[str, str]:
        """
        get all existing language names for this language
        @param lang_code:
        @return:
        """
        indices = [f"lang.{lang}" for lang in self.get_added_languages()]
        table = self.get_table(FRONTEND_MESSAGE_COMPONENT)
        res = self.execute(
            select(
                [table.columns[MESSAGE_TABLE_INDEX_COLUMN], table.columns[lang_code]]
            ).where(table.columns[MESSAGE_TABLE_INDEX_COLUMN].in_(indices))
        ).fetchall()
        return {index_name[0]: index_name[1] for index_name in res}

    def update_language_status(self, lang, active: bool = False) -> dict:
        language_status = {
            "lang_code": lang,
            "active": active,
            "fe_msg_count": None,
            "be_msg_count": None,
        }
        for component in [FRONTEND_MESSAGE_COMPONENT, BACKEND_MESSAGE_COMPONENT]:
            msgs = self.get_component(component, lang)
            count = 0
            for (index, msg) in msgs:
                if msg != "" and msg is not None:
                    count += 1
            language_status[f"{component}_msg_count"] = count

        status_table = self.get_table(MESSAGES_STATUSES)
        existing_row = self.execute(
            status_table.select().where(status_table.columns["lang_code"] == lang)
        ).fetchone()
        # todo this is sketchy. what are the counts for anyway.
        # makes a language active by default? and if not makes a strange insertion.
        # could be made more elegant if any useful
        if not existing_row:
            self.execute(status_table.insert(), language_status)
        else:
            language_status["active"] = existing_row[1]
            self.execute(
                status_table.update().where(status_table.columns["lang_code"] == lang),
                language_status,
            )
        return language_status

    def get_lang_status(self, lang_code: str) -> Optional[Tuple]:
        status_table = self.get_table(MESSAGES_STATUSES)
        return self.execute(
            status_table.select().where(status_table.columns["lang_code"] == lang_code)
        ).fetchone()

    def change_lang_status(self, lang_code: str, active: bool) -> Optional[bool]:
        """
        change language status in the status table and the cache.
        @param lang_code:
        @param active:
        @return: active
        """
        # update the table
        status_table = self.get_table(MESSAGES_STATUSES)
        self.execute(
            status_table.update().where(status_table.columns["lang_code"] == lang_code),
            {"active": active},
        )
        # update the cache
        self.root_sw.app.state.language_active_statuses[lang_code] = active
        return active

    def get_all_statuses(self):
        status_table = self.get_table(MESSAGES_STATUSES)
        return self.execute(status_table.select()).fetchall()

    def delete_language(self, language_code):
        all_languages = list(
            filter(lambda l: l != language_code, self.get_added_languages())
        )

        components = [BACKEND_MESSAGE_COMPONENT, FRONTEND_MESSAGE_COMPONENT]
        for component in components:
            # sqlite cannot drop columns, so we create a temp new one, with all data except the column to delete
            # delete existing, and rename the temp to original
            temp_name = f"{component}_temp"
            self.execute(
                f"CREATE TABLE {temp_name} AS SELECT "
                f"{', '.join([MESSAGE_TABLE_INDEX_COLUMN] + all_languages)} FROM {component}"
            )
            table = self.get_table(component)
            table.drop()
            self.execute(f"ALTER TABLE {temp_name} RENAME TO {component}")

        self.reflect_components()

        status_table = self.get_table(MESSAGES_STATUSES)
        self.execute(
            status_table.delete().where(
                status_table.columns["lang_code"] == language_code
            )
        )

        del self.root_sw.app.state.language_active_status[language_code]

    def remove_words(self, component: L_MESSAGE_COMPONENT, indices: List[str]):
        table = self.get_table(component)
        self.execute(
            table.delete().where(table.columns[MESSAGE_TABLE_INDEX_COLUMN].in_(indices))
        )

    def get_history(
            self,
            language_code: str,
            component: L_MESSAGE_COMPONENT,
            page: int = 0,
            words_per_page: int = 100,
            discard_keys: List[str] = (),
    ):
        table = self.get_table(MESSAGES_CHANGES)
        rows = self.execute(
            table.select()
                .where(table.columns["lang_code"] == language_code)
                .where(table.columns["component"] == component)
                .offset(page * words_per_page)
                .limit(words_per_page)
                .order_by(desc(table.columns["timestamp"]))
        ).fetchall()

        indices = []
        prev_messages = []
        for row in rows:
            res_dict = {}
            for k, v in row.items():
                if k not in discard_keys:
                    # we have to do this (keys to str) because it uses a float
                    # as the timestamp key when just calling dict(row)... !?!
                    res_dict[str(k)] = v
                if k == "timestamp":
                    res_dict[str(k)] = datetime.fromtimestamp(int(v)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
            indices.append(res_dict[MESSAGE_TABLE_INDEX_COLUMN])
            prev_messages.append(res_dict)

        res = self.t_list(indices, language_code, component)

        for msg in prev_messages:
            # check if message with index still exists
            if act_msg := res.get(msg[MESSAGE_TABLE_INDEX_COLUMN]):
                # check if we have the selected language (and not the default language)
                if act_msg[0] == language_code:
                    msg["msg"] = act_msg[1]
        return prev_messages
