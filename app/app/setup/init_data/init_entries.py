from logging import getLogger
from os.path import join
from typing import List, Optional

from app.models.orm import RegisteredActor, Entry
from app.models.schema.template_code_entry_schema import TemplateBaseInit
from app.services.service_worker import ServiceWorker
from app.services.entry import entry_descriptor
from app.settings import INIT_DOMAINS_FOLDER
from app.util.consts import TEMPLATE, CODE, SCHEMA
from app.util.files import JSONPath, glob_json

logger = getLogger(__name__)


def init_entries(domain, sw: ServiceWorker, actor: RegisteredActor) -> None:
    """
    Initializes all entries from a domain

    @param domain: name of the domain
    @param sw: root service
    @param actor: actor who is set as creator of all entries
    """
    all_entries_models: List[TemplateBaseInit] = []
    domain_folder = join(INIT_DOMAINS_FOLDER, domain.name)

    entrytypes = [SCHEMA, TEMPLATE, CODE]

    for entrytype in entrytypes:
        logger.debug(f"Files of type: {entrytype}:")
        entrytype_base_folder = join(domain_folder, entrytype)
        entrytype_files = glob_json(entrytype_base_folder, True)

        for file in (JSONPath(_) for _ in entrytype_files):
            logger.debug(f"{file}")
            entry_data: Optional[dict] = sw.data.read_base_entry_file(file)
            if entry_data:
                base_model = sw.data.create_base_model(entry_data)
                if base_model:
                    # check if a slug-entry with the same slug already exists already
                    if existing := sw.data.get_existing_in_entries_base_cache(base_model.slug):
                        if existing.domain != base_model.domain:
                            logger.warning(
                                f"Entry {entry_descriptor(base_model)} already exists in domain '{existing.domain}'."
                                f" Skipping")
                            continue
                    logger.debug(
                        f"created base-model, {base_model.type}, {base_model.slug}"
                    )
                    all_entries_models.append(base_model)

    # resolve reference dependencies so that their are added in proper order
    logger.debug(f"resolving dependencies for {len(all_entries_models)} entries")
    logger.debug(f"references: {[e.entry_refs for e in all_entries_models]}")
    ordered_models: List[TemplateBaseInit] = sw.data.resolve_dependencies(
        all_entries_models
    )
    logger.info(
        f"{domain.name}: Order of init entries data: {[e.slug for e in ordered_models]}"
    )
    for base_model in ordered_models:
        sw.data.init_base_entry(base_model, actor, domain)
