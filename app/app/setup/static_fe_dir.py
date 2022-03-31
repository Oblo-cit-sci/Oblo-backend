import os
from logging import getLogger
from os.path import isdir, join

from fastapi import FastAPI
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from app.services.service_worker import ServiceWorker
from app.settings import BASE_DIR, env_settings
from app.util.consts import TEST, PROD

logger = getLogger(__name__)


def add_static_fe_dir(app):

    app_dir = env_settings().APP_DIR
    if app_dir:
        app_dir = join(BASE_DIR, app_dir)
        app_route = env_settings().APP_ROUTE
        if isdir(app_dir):
            logger.info("mounting frontend dir:%s to:%s" % (app_dir, app_route))
            app.mount(
                app_route,
                StaticFiles(directory=app_dir, html=True, check_dir=True),
                name="frontend",
            )
        else:
            if env_settings().ENV in [TEST, PROD]:
                logger.warning(
                    f"frontend app directory {os.path.abspath(app_dir)} does not exist, skipping to serve it as static directory. "
                    "You can get the latest version from https://opentek.eu/fe_releases/latest.zip and unzipping"
                    "it into the project folder (with default settings, so that the dir 'fe' is next to main.py",
                )
            logger.warning(f"No frontend app directory: {os.path.abspath(app_dir)}")
    else:
        logger.info("no APP_DIR config given. running with api only")


async def domain_reroute(request):
    return RedirectResponse(
        url=f"{env_settings().HOST}/domain?f={request['path'][1:]}&{str(request.query_params)}"
    )


def add_domain_redirect_pages(sw: ServiceWorker, app: FastAPI):
    domain_names = [dm.name for dm in sw.domain.get_all_meta()]
    for domain in domain_names:
        app.add_route(path="/" + domain, route=domain_reroute, methods=["GET"])
