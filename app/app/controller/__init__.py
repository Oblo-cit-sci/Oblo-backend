from fastapi import APIRouter

from .plugin_ctrl import router as plugin_router
from .actor_ctrl import router as actor_router
from .oauth_ctrl import router as oauth_router
from .basic_ctrl import router as basic_router
from .config_ctrl import router as config_router
from .domain_ctrl import router as domain_router
from .entries_ctrl import router as entries_router
from .entry_ctrl import router as entry_router
from .entry_slug_ctrl import router as entry_slug_router
from .entry_files_ctrl import entry_uuid_attachment_router, entry_slug_attachment_router
from .language_ctrl import router as language_router
from .sse_connection_ctrl import router as sse_router
from .util_ctrl import router as util_router
from ..settings import env_settings

base_router = APIRouter(prefix=env_settings().BASE_ROUTER_PREFIX)

for router in [
    basic_router,
    oauth_router,
    domain_router,
    actor_router,
    entry_router,
    entry_slug_router,
    entry_uuid_attachment_router,
    entry_slug_attachment_router,
    entries_router,
    sse_router,
    plugin_router,
    language_router,
    config_router,
    util_router,
]:
    base_router.include_router(router)

if env_settings().is_dev():
    try:
        from .test_ctrl import router as test_router

        base_router.include_router(test_router)
        from .dev_ctrl import router as dev_router

        base_router.include_router(dev_router)
    except ImportError as err:
        test_router = None
        dev_router = None
        pass


def route_for(ctrl_class: APIRouter, route_method: str):
    return env_settings().BASE_ROUTER_PREFIX + ctrl_class.url_path_for(route_method)
