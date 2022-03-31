from glob import glob
from logging import getLogger
from os.path import join, isdir, basename
from typing import List, Optional, Literal, Set, Tuple, Dict

import dirsync
from jsonschema import ValidationError
from orjson import JSONDecodeError
from pydantic import ValidationError as PydanticValidationError
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app import settings
from app.models.orm import RegisteredActor, Entry, Domain
from app.models.schema.template_code_entry_schema import TemplateBaseInit, TemplateLang
from app.services.entry import join_entrytype_filter, entry_descriptor
from app.services.service_worker import ServiceWorker
from app.settings import (
    env_settings,
    INIT_DOMAINS_FOLDER,
    BASE_STATIC_FOLDER,
    INIT_DATA_FOLDER,
)
from app.util.consts import (
    DOMAIN,
    TYPE,
    LANGUAGE,
    SLUG,
    SCHEMA,
    CONFIG,
    FROM_FILE,
    TITLE,
    VALUE_TREE,
    VALUE_LIST,
    BASE_CODE, BASE_SCHEMA_ENTRIES, CONCRETE_ENTRIES,
)
from app.util.exceptions import ApplicationException
from app.util.files import JSONPath

logger = getLogger(__name__)


class DataServiceWorker:
    """
    Services that help loading and initializing initial data
    - resolve_dependencies(entries)
    - get_init_file

    """

    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session
        # this is created first time init_entries is called and cleared at the end
        self.entries_base_schema_cache: List[Entry] = join_entrytype_filter(self.root_sw.entry.base_q(),
                                                                            BASE_SCHEMA_ENTRIES).all()
        self.entries_concrete_cache: List[Entry] = join_entrytype_filter(self.root_sw.entry.base_q(),
                                                                         CONCRETE_ENTRIES).all()

    def clear_init_entries_cached(self):
        self.entries_base_schema_cache = []
        self.entries_concrete_cache = []

    def get_existing_in_entries_base_cache(self, slug: str) -> Optional[Entry]:
        find = list(filter(lambda e: e.slug == slug, self.entries_base_schema_cache))
        if find:
            return find[0]
        return None

    def get_existing_in_entries_concrete_cache(self, slug: str, language: str) -> Optional[Entry]:
        find = list(filter(lambda e: e.slug == slug and e.language == language, self.entries_concrete_cache))
        if find:
            return find[0]
        return None

    # noinspection PyMethodMayBeStatic
    def resolve_dependencies(
            self, entries: List[TemplateBaseInit], raise_error: bool = True
    ):
        """
        takes a list of entry-data (code and templates) and calculates the dependencies.
        An entry depends on another one, when it is its template or a reference.
        during initialization the dependent entry must be create before the depending one.
        the result are the same entries but sorted, so that they will not fail.
        throws an exception if the dependencies are circular.

        @param entries:
        @param raise_error: (default: True)
        @return:
        """
        all_slugs = {e.slug for e in entries}
        # for each slug a set of slugs, which it depends on
        dependencies_map: Dict[str: Set[str]] = {}
        for entry in entries:
            try:
                deps = set()
                if entry.template:
                    deps.add(entry.template.slug)
                deps.update(set([ref.dest_slug for ref in entry.entry_refs]))
                # we only resolve dependencies within the domain. all others are ignored
                dependencies_map[entry.slug] = set(
                    filter(lambda e: e in all_slugs, deps)
                )
            except AttributeError:
                raise ApplicationException(
                    HTTP_500_INTERNAL_SERVER_ERROR,
                    f"Entry data not in the right shape: {entry.slug}",
                )
        """
        push all slugs to resolved that have no (more) deps
        if none can be added. raise error for circular dependency
        remove em from the dependency map
        remove from them from all other dependency lists
        """
        resolved = []
        while dependencies_map:
            to_add = [
                slug for slug in dependencies_map.keys() if not dependencies_map[slug]
            ]
            if not to_add:
                if raise_error:
                    raise ApplicationException(
                        HTTP_500_INTERNAL_SERVER_ERROR,
                        f"Circular dependencies: {dependencies_map}",
                    )
                else:
                    break
            resolved.extend(to_add)
            for e in to_add:
                del dependencies_map[e]
                for ee in dependencies_map.values():
                    if e in ee:
                        ee.remove(e)
        return list(sorted(entries, key=lambda e: resolved.index(e.slug)))

    # TODO similar already in entry_sw
    # noinspection PyMethodMayBeStatic
    def get_init_file(
            self,
            domain: str,
            _type: Literal["domain", "code", "template"],
            slug: Optional[str] = str,
            lang: Optional[str] = None,
            **kwargs,
    ) -> JSONPath:
        """
        Get a init-file, specified by the parameters.
        @param domain: domain
        @param _type: domain|code|template
        @param slug: entry slug (will only be considered when type is code or template
        @param lang: language, can be omitted to get domain-meta or entry-base
        @param kwargs:
        @return:
        """
        path = join(INIT_DOMAINS_FOLDER, domain)
        if lang:
            path = join(path, "lang", lang)
        if _type == DOMAIN:
            return JSONPath(join(path, "domain.json"), **kwargs)
        else:
            return JSONPath(join(path, _type, slug + ".json"), **kwargs)

    def read_init_file(
            self,
            domain: str,
            _type: Literal["domain", "code", "template"],
            slug: str,
            lang: Optional[str] = None,
    ) -> dict:
        """
        reads an init-entry-file given by the identifier (domain, language, type, slug)
        The type can also be domain, in which case the slug is ignored
        @param domain: domain name
        @param _type: template, code, regular
        @param slug: entry slug
        @param lang: language
        @return: json data
        """
        return self.get_init_file(domain, _type, slug, lang).read()

    def get_part_from_entry_file(
            self,
            fp: JSONPath,
            parts: Set[Literal["*", "domain", "type", "language", "slug"]],
    ) -> List[str]:
        """
        not used atm. get a part of the identifier.
        @param fp: JSONPath: json file path
        @param parts: which parts? *=all, domain, type, language, slug
        @return: list of parts in the order given as params or domain, type, language, slug
        """
        result = set()
        for p in parts:
            if p == "*":
                return self.get_part_from_entry_file(fp, {DOMAIN, TYPE, LANGUAGE, SLUG})
            if p == DOMAIN:
                result.add(fp.parts[-5])
            elif p == TYPE:
                result.add(fp.parts[-2])
            elif p == LANGUAGE:
                result.add(fp.parts[-3])
            elif p == SLUG:
                result.add(fp.stem)
            else:
                logger.warning(f"unknown part: {p}")
        return list(result)

    def init_entries_sort_default_lang_first(
            self,
            file_paths: List[JSONPath],
            language: Optional[str] = env_settings().DEFAULT_LANGUAGE,
    ) -> Tuple[List[JSONPath], bool]:
        """
        puts the file with the set language to the beginning.
        return true if a file for the language exists otherwise false
        @param file_paths:
        @param language:
        @return:
        """
        source_entry = None
        rest = []
        if not file_paths:
            return [], True
        for fp in file_paths:
            if self.get_part_from_entry_file(fp, {LANGUAGE})[0] == language:
                source_entry = fp
            else:
                rest.append(fp)
        if not source_entry:
            logger.warning(
                f"No filepath for entry in language: {language} for "
                f"{self.get_part_from_entry_file(file_paths[0], {DOMAIN, TYPE, SLUG})}"
            )
            return rest, False
        else:
            return [source_entry] + rest, True

    # noinspection PyMethodMayBeStatic
    def sync_folder(self, source_dir: str, dest_dir: str) -> None:
        """
        sync a folder. used to copy files from init_data folders to static folders
        @param source_dir:
        @param dest_dir:
        """
        dirsync.sync(
            source_dir,
            dest_dir,
            "sync",
            **{"create": True, "purge": True, "logger": logger},
        )

    # noinspection PyMethodMayBeStatic
    def sync_domain_assets(self, domain_name):
        """
        copies the assets of a domain to the static folder. `domains/<domain_name>/assets
        @param domain_name: name of the domain
        """
        source_dir = join(INIT_DOMAINS_FOLDER, domain_name, "assets")
        if isdir(source_dir):
            dest_dir = join(BASE_STATIC_FOLDER, "assets", "domains", domain_name)
            dirsync.sync(
                source_dir,
                dest_dir,
                "sync",
                **{"create": True, "purge": True, "logger": logger},
            )

    # noinspection PyMethodMayBeStatic
    def sync_files(self, source_folder, destination_folder, files: List[str]) -> None:
        """
        not used atm. wouldn't work like that.
        see visitor_avatar in initial_file_setup
        which syncs the whole dir but sets only to the filename
        also here if the name would be different it would need to do a rename (well well, not so cool)
        """
        for file in files:
            dirsync.sync(
                source_folder,
                destination_folder,
                "sync",
                **{"create": True, "logger": logger, "only": [file]},
            )

    def init_base_by_path(
            self, path: str, actor: RegisteredActor, domain_meta: Domain
    ) -> Optional[Entry]:
        """
        todo. there should also be a call from a controller...
        """
        entry_data: Optional[dict] = self.read_base_entry_file(
            JSONPath(join(INIT_DOMAINS_FOLDER, path))
        )

        try:
            base_model = self.create_base_model(entry_data)
            if base_model:
                return self.init_base_entry(base_model, actor, domain_meta)

        except (PydanticValidationError, ApplicationException) as err:
            logger.error(
                f".init_entries updating entry: {entry_descriptor(entry_data)}"
            )
            logger.error(err)
            return

    # noinspection PyMethodMayBeStatic
    def read_base_entry_file(self, file: JSONPath) -> Optional[dict]:
        rel_path = file.relative_to(INIT_DOMAINS_FOLDER)
        domain, entrytype = rel_path.parts[:2]
        type_ = f"base_{entrytype}" if entrytype != SCHEMA else SCHEMA
        try:
            data = file.read_insert(
                insert={
                    DOMAIN: domain,
                    TYPE: type_,
                    CONFIG: {FROM_FILE: True},
                    TITLE: "",
                },
                setdefault={"rules": {}},
            )

            # set slug based on filename if its not that
            if (defined_slug := data.get(SLUG)) != file.stem:
                if defined_slug is not None:  # if its omitted we dont warn...
                    logger.warning(
                        f"slug defined in file {defined_slug} does not match filename: {file.stem}!"
                    )
                data[SLUG] = file.stem

            return data
        except JSONDecodeError as err:
            logger.error(err)
            logger.error(f"Skipping {file}")
        return None

    # noinspection PyMethodMayBeStatic
    def create_base_model(self, base_data: dict) -> Optional[TemplateBaseInit]:
        try:
            base_model = TemplateBaseInit.parse_obj(base_data)
            base_model.entry_refs = self.root_sw.entry.get_entry_references(base_model)
            return base_model
        except PydanticValidationError as err:
            logger.error(f"error {entry_descriptor(base_data)}:")
            logger.error(err)
            return

    def init_base_entry(
            self, base_model: TemplateBaseInit, actor: RegisteredActor, domain_meta: Domain
    ) -> Optional[Entry]:
        """
        calls update_or_insertlang__get_model__merge_insert_o_update
        """
        entrytype = base_model.type
        slug = base_model.slug
        domain_folder = join(INIT_DOMAINS_FOLDER, base_model.domain)
        identifier = entry_descriptor(base_model)
        logger.debug(f"Checking entry: {identifier}")

        if base_model.type == BASE_CODE:
            template_slug = base_model.template.slug
            # todo also in the end, this should be more flexible
            if template_slug in [VALUE_TREE, VALUE_LIST]:
                base_model.rules.code_schema = base_model.template.slug
                # todo actually look it up
                base_model.template.version = 1

        # copy static folders
        entry_files_folder = join(domain_folder, "entry_files")
        entry_files_dir = join(entry_files_folder, slug)
        if isdir(entry_files_dir):
            logger.info(f"copying entry dir {entry_files_dir}")
            dest = join(settings.ENTRY_DATA_FOLDER, base_model.slug)
            self.sync_folder(entry_files_dir, dest)

        try:
            base_entry = self.root_sw.template_codes.update_or_insert(base_model, actor)
        except (PydanticValidationError, ApplicationException) as err:
            logger.error(f".init_entries updating entry: {identifier}")
            logger.error(err)
            return
        except Exception as err:
            logger.error(f"Unknown error for: {identifier}:")
            logger.error(err)
            return

        if entrytype == SCHEMA:
            return
        concrete_type = entrytype[len("base_"):]
        lang_entrytype_files = glob(
            domain_folder + f"/lang/*/{concrete_type}/{slug}.json"
        )

        # we use this in order to add the tags in the right order
        (
            lang_entrytype_files,
            default_e_available,
        ) = self.init_entries_sort_default_lang_first(
            [JSONPath(_) for _ in lang_entrytype_files], language=domain_meta.default_language
        )
        if not default_e_available:
            logger.warning(f"Entry in default language not available: {identifier}")
            return
        if len(lang_entrytype_files) == 0:
            logger.warning(f"Entry in no language: {identifier}")
        new_entries = []
        lang_files_languages = []
        for lang_file in lang_entrytype_files:
            language = basename(lang_file.parents[1])
            lang_files_languages.append(language)
            file_ident = lang_file.relative_to(INIT_DATA_FOLDER)
            logger.debug(f"entry-language file: {file_ident}")

            entry: Optional[Entry] = self.init_lang_entry_from_file(
                base_entry, lang_file, actor
            )

            if entry:
                new_entries.append(entry)
                lang_files_languages.append(entry.language)
            else:
                if lang_file == lang_entrytype_files[0]:
                    logger.warning(
                        f"Without the entry in the default language other files are not added neither: {identifier}"
                    )
                    break

        # connect them in the translation table
        # actually redundant cuz we grab them by their slug...
        if len(new_entries) > 1:
            source_entry = new_entries[0]
            for e in new_entries[1:]:
                try:
                    self.root_sw.translation.create_translation(
                        source_entry, e, commit=False
                    )
                except ApplicationException:
                    pass

        # update entries in database which have no file, or where the file is outdated
        # todo probably not needed. assuming that db entries
        # entry_lang_objects: List[Entry] = self.root_sw.template_codes.get_all_concretes(slug)
        # for db_entry in entry_lang_objects:
        #     ident = f"{slug}: {db_entry.language}"
        #     if db_entry.language in lang_files_languages:
        #         continue
        #     logger.info(f"Updating database entry object: {ident}")
        #     l_data = EntryLang.from_orm(db_entry).dict()
        #     l_data[CONFIG] = db_entry.config  # add since its not part of EntryLang
        #     entry = self.lang__get_model__merge_insert_o_update(base_entry, l_data, actor)
        #     # change it to draft if it wasn't updated. so it needs to be updated on the translation page
        #     # todo could be env_settings. check if it works and if it does the wanted effect.
        #      dont show them anymore...
        #     if not entry:
        #         db_entry.status = DRAFT

        self.root_sw.template_codes.versioning.check_can_smash_version_changes(base_entry)
        self.db_session.commit()

        return base_entry

    def init_lang_entry_from_file(
            self, base_entry: Entry, lang_file: JSONPath, actor: RegisteredActor
    ) -> Optional[Entry]:
        rel_path = lang_file.relative_to(INIT_DOMAINS_FOLDER)
        (
            domain,
            _,
            language,
            type_,
        ) = rel_path.parts[:4]

        read_from_file = True

        existing_entry: Entry = self.root_sw.template_codes.get_by_slug_lang(
            base_entry.slug, language, raise_error=False
        )
        if existing_entry:
            # file-data is outdated
            if not existing_entry.config.get(FROM_FILE):
                read_from_file = False
                logger.warning(f"File outdated for {rel_path}. skipping")
            else:
                read_from_file = True
        if read_from_file:
            return self.init_concrete_by_path(lang_file, actor, base_entry)

    # noinspection PyMethodMayBeStatic
    def _read_concrete_entry_file(self, file: JSONPath) -> Optional[dict]:
        rel_path = file.relative_to(INIT_DOMAINS_FOLDER)
        (
            domain,
            _,
            language,
            type_,
        ) = rel_path.parts[:4]
        slug = file.stem
        # TODO REMOVE FROM_LOCAL_FILE.... ITS LOCATION SHOULD ALWAYS BE OBVIOUS
        # TODO ALSO SLUG IS ALWAYS == FILENAME FOR THIS TO WORK...
        try:
            return file.read_insert(
                insert={
                    TYPE: type_,
                    CONFIG: {FROM_FILE: True},
                    DOMAIN: domain,  # just for the identifier
                    SLUG: slug,  # just for the identifier
                    LANGUAGE: language,
                }
            )

        except (JSONDecodeError, ValidationError) as err:
            logger.error(err)
            logger.warning(f"Skipping language file: {domain}/{language}/{slug}")

    def init_concrete_by_path(
            self, path: JSONPath, actor: RegisteredActor, base_entry: Optional[Entry]
    ) -> Optional[Entry]:
        lang_data: Optional[dict] = self._read_concrete_entry_file(path)
        if not base_entry:
            base_entry = self.root_sw.template_codes.get_base_schema_by_slug(
                lang_data[SLUG]
            )
        if lang_data:
            return self.lang__get_model__merge_insert_o_update(
                base_entry, lang_data, actor
            )

    # noinspection PyMethodMayBeStatic
    def lang__get_model__merge_insert_o_update(
            self, base_entry: Entry, l_data: dict, actor: RegisteredActor
    ) -> Optional[Entry]:
        """
        compact part, for something that is either done with the base a bit expanded or language data in a loop
        @param base_entry:
        @param l_data:
        @param actor:
        @return:
        """
        # l_identifier = entry_descriptor(l_data)
        base_model = TemplateBaseInit.from_orm(base_entry)
        # logger.debug(f"Checking: {l_identifier}")
        try:
            l_model = TemplateLang.parse_obj(l_data)
        except PydanticValidationError as err:
            logger.error(f"Could not parse language data: {entry_descriptor(l_data)}")
            logger.error(err)
            return
        # logger.debug("EntryLang parsed")
        full_model = self.root_sw.template_codes.merge_base_lang(base_model, l_model)
        if full_model:
            return self.root_sw.template_codes.update_or_insert(full_model, actor)
