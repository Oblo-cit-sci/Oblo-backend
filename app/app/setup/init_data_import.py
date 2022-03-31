from glob import glob
from logging import getLogger
from os.path import basename, join
from typing import Dict, List, Optional, Tuple

import orjson
from pydantic import ValidationError

from app.models.orm import Entry, RegisteredActor
from app.models.schema.template_code_entry_schema import EntryIn
from app.services.entry import add_with_actor, set_template
from app.services.service_worker import ServiceWorker
from app.settings import INIT_DOMAINS_FOLDER, env_settings
from app.setup.init_data.init_domains import init_domains
from app.util.consts import PUBLISHED
from app.util.db_util import commit_and_new
from app.util.files import read_orjson

logger = getLogger(__name__)


def init_data_import(sw: ServiceWorker, actor: RegisteredActor):
    """
    Initializes the data in init, domains & entries, copies their assets to the static folder
    @param sw: service
    """
    logger.info(
        f"init data import settings:\n- load domains: {env_settings().INIT_DOMAINS}, "
        f"templates and codes: {env_settings().INIT_TEMPLATES_CODES}"
    )
    if env_settings().INIT_DOMAINS:
        init_domains(sw, actor)
    sw.data.clear_init_entries_cached()


def prepare_for_import(entry_data: Dict):
    for k in [
        "app_version",
        "refs",
        "creation_ts",
        "last_edit_ts",
        "downloads",
        "draft_no",
        "status",
        "version",
        "local",
    ]:
        if k in entry_data:
            del entry_data[k]
    if "entry_refs" not in entry_data:
        entry_data["entry_refs"] = []


