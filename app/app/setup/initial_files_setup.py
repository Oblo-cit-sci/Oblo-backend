from logging import getLogger
from os import listdir, makedirs
from os.path import isdir, join, exists
from pathlib import Path
from shutil import rmtree
from typing import List

import dirsync as dirsync
from sqlalchemy import or_, and_

from app import settings
from app.models.orm import Entry, RegisteredActor
from app.services.service_worker import ServiceWorker
from app.settings import COMMON_DATA_FOLDER, USER_DATA_FOLDER, BASE_DIR
from app.util.common import uuid4_regex_match
from app.util.consts import CODE, TEMPLATE

logger = getLogger(__name__)


def init_files(sw: ServiceWorker):
    init_folders()
    remove_redundant_actor_folders(sw)
    remove_redundant_entry_folders(sw)
    visitor_avatar()


def init_folders():
    for folder in [
        settings.BASE_DATA_FOLDER,
        settings.INIT_DATA_FOLDER,
        settings.ENTRY_DATA_FOLDER,
        settings.USER_DATA_FOLDER,
        join(settings.USER_DATA_FOLDER, "visitor"),
        settings.COMMON_DATA_FOLDER,
        settings.DOMAINS_IMAGE_FOLDER,
        settings.TEMP_FOLDER,
        settings.TEMP_APP_FILES,
    ]:
        if not isdir(folder):
            makedirs(folder)


def remove_redundant_actor_folders(sw: ServiceWorker) -> List[str]:
    """
    remove folders of actors that are not in the db
    @param sw: ServiceWorker
    @return: registered names of removed actors
    """
    all_actors_folder = listdir(settings.USER_DATA_FOLDER)
    for actor in sw.db_session.query(RegisteredActor):
        actor_path = sw.actor.get_actor_path(actor.registered_name)
        if isdir(actor_path):
            all_actors_folder.remove(actor.registered_name)
    # existing_actor_folder.remove()
    logger.debug(f"removing actor folder for: {all_actors_folder}")
    for redundant_actor_folder in all_actors_folder:
        rmtree(sw.actor.get_actor_path(redundant_actor_folder))
    return all_actors_folder


def remove_redundant_entry_folders(sw: ServiceWorker):
    entry_folder = listdir(settings.ENTRY_DATA_FOLDER)
    by_uuid = []
    by_slug = []
    for e in entry_folder:
        if uuid4_regex_match(e):
            by_uuid.append(e)
        else:
            by_slug.append(e)

    t_c = [CODE, TEMPLATE]
    # noinspection PyUnresolvedReferences
    for db_e in (
        sw.db_session.query(Entry)
        .filter(
            or_(
                and_(Entry.type.in_(t_c), Entry.slug.in_(by_slug)),
                Entry.uuid.in_(by_uuid),
            )
        )
        .all()
    ):
        if db_e.type in t_c:
            if (slug_ := db_e.slug) in by_slug:
                by_slug.remove(slug_)
        elif (uuid_ := db_e.uuid) in by_uuid:
            by_uuid.remove(uuid_)
    for folder in by_uuid + by_slug:
        logger.debug(f"removing entry-folder: {folder}")
        if isdir(folder):
            rmtree(folder)


def visitor_avatar():
    avatar_img_src_path = join(COMMON_DATA_FOLDER, "avatar.jpg")
    if not exists(avatar_img_src_path):
        logger.warning(f"visitor avatar not found in {Path(avatar_img_src_path).relative_to(BASE_DIR)}")
    visitor_data_folder = join(USER_DATA_FOLDER, "visitor")
    dirsync.sync(
        COMMON_DATA_FOLDER,
        visitor_data_folder,
        "sync",
        **{"only": ["avatar.jpg"], "logger": logger},
    )