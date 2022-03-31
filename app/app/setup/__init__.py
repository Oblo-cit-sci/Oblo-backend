import os

from fastapi import FastAPI
from slowapi import Limiter
from sqlalchemy.orm import Session
from starlette.staticfiles import StaticFiles

from app import controller
from app.app_logger import get_logger
from app.middlewares import add_middlewares
from app.services.service_worker import ServiceWorker
from app.settings import BASE_STATIC_FOLDER, env_settings, INIT_DOMAINS_FOLDER
from app.setup.cache import init_cache
from app.setup.data_migration import data_migration
from app.setup.db_setup import setup_default_actors
from app.setup.init_data.init_message_tables import (
    messages_db_exists,
    setup_translations,
)
from app.setup.init_data_import import init_data_import
from app.setup.initial_files_setup import (
    remove_redundant_actor_folders,
    init_folders,
    remove_redundant_entry_folders,
    visitor_avatar,
    init_files,
)
from app.setup.static_fe_dir import add_static_fe_dir, add_domain_redirect_pages
from app.setup.tests import clear_db
from app.util.consts import NO_DOMAIN
from app.util.db_util import commit_and_new
from app.util.exceptions import (
    ApplicationException,
    application_exception_handler,
    exception_handler,
)


logger = get_logger(__name__)

class ObloAppState():
    language_active_statuses: dict[str,bool] = {}
    limiter: Limiter
    only_one_domain: bool


def setup_all(app: FastAPI):
    logger.info("setup")
    app.state = ObloAppState()
    add_middlewares(app)

    app.add_exception_handler(ApplicationException, application_exception_handler)
    app.add_exception_handler(Exception, exception_handler)

    app.include_router(controller.base_router)

    # PRE-SERVICE
    # setup_oauth()
    # SERVICE
    session: Session = commit_and_new()

    new_db: bool = not messages_db_exists()
    sw = ServiceWorker(session, app=app)

    setup_translations(app, sw, new_db)

    if env_settings().ENV == "test" and env_settings().RESET_TEST_DB:
        logger.info("test environment. clearing db")
        clear_db(session)

    admin = setup_default_actors(sw)
    init_files(sw)

    # init domains, their entries and plugins
    if os.path.isdir(INIT_DOMAINS_FOLDER):
        init_data_import(sw, admin)
    else:
        logger.warning(f"INIT_DOMAINS_FOLDER does not exist: {INIT_DOMAINS_FOLDER}")

    # todo maybe somewhere else, so it updates in case domains are added.
    app.state.only_one_domain = (
        len(
            list(
                filter(
                    lambda dmeta: dmeta.is_active and dmeta.name != NO_DOMAIN,
                    sw.domain.get_all_meta(),
                )
            )
        )
        == 1
    )

    app.mount("/static", StaticFiles(directory=BASE_STATIC_FOLDER), name="static")
    add_domain_redirect_pages(sw, app)
    add_static_fe_dir(app)

    init_cache(sw)

    logger.info("setup done")
    logger.info(f"Data migration: {env_settings().DATA_MIGRATION}")
    if env_settings().DATA_MIGRATION:
        data_migration(session)
    if env_settings().RUN_APP_TESTS:
        try:
            from app.setup.tests import run_app_tests
            run_app_tests(app, sw)
        except ImportError:
            logger.warning("app tests not found")
    session.close()
