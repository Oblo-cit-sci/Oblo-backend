from logging import getLogger

from fastapi import APIRouter, Depends, Body
from starlette.responses import Response
from starlette.status import (
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from app.dependencies import is_admin, get_sw
from app.globals import registered_plugins, available_plugins
from app.models.orm import RegisteredActor
from app.models.schema.response import simple_message_response
from app.services.service_worker import ServiceWorker
from app.util.exceptions import ApplicationException
from app.util.plugins import activate_plugin, deactivate_plugin

router = APIRouter(prefix="/plugin", tags=["Plugin"])

logger = getLogger(__name__)


@router.get("/list_plugins")
async def list_plugins(_: RegisteredActor = Depends(is_admin)):
    return {"available": list(available_plugins), "active": list(registered_plugins)}


@router.get(
    "/set_plugin",
    response_model=simple_message_response,
    response_model_exclude_none=True,
)
async def set_plugin(
    plugin_name: str, set_on: bool, admin: RegisteredActor = Depends(is_admin)
):
    if set_on:
        if plugin_name in registered_plugins:
            return simple_message_response("Plugin is already active")
        else:
            success = activate_plugin(plugin_name)
            return simple_message_response(
                f"activation {'successful' if success else 'failed'}"
            )
    else:
        if not deactivate_plugin(plugin_name):
            return simple_message_response("Plugin is not active")
        else:
            return simple_message_response("Plugin deactivated")


@router.post("/{plugin_name}")
async def plugin_call(
    plugin_name: str,
    response: Response,
    data: dict = Body(None),
    sw: ServiceWorker = Depends(get_sw),
):
    if plugin_name in registered_plugins:
        try:
            result = registered_plugins[plugin_name](data)
            return result
        except ApplicationException as app_exc:
            raise app_exc
        except Exception as err:
            logger.exception(err)
            raise ApplicationException(
                HTTP_500_INTERNAL_SERVER_ERROR, "plugin execution failed"
            )
    else:
        logger.warning(f"unknown plugin requested: {plugin_name}")
        response.status_code = HTTP_422_UNPROCESSABLE_ENTITY
        return sw.error_response(HTTP_422_UNPROCESSABLE_ENTITY, "plugin does not exist")
