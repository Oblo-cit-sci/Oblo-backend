import logging
from logging import getLogger
from typing import Dict

from starlette.websockets import WebSocket, WebSocketState

from app.models.orm import RegisteredActor

handler: Dict[str, WebSocket] = {}

logger = getLogger(__name__)

getLogger().setLevel(logging.DEBUG)


def add_actor(actor: RegisteredActor, websocket: WebSocket):
    name = actor.registered_name
    logger.debug(f"adding websocket connection for {name}")
    if name in handler:
        return False
    else:
        handler[name] = websocket


def remove_actor(actor: RegisteredActor):
    name = actor.registered_name
    logger.debug(f"removing websocket connection for {name}")
    if name in handler:
        del handler[name]


def get_ws_connection(actor: RegisteredActor):
    name = actor.registered_name
    if name in handler:
        ws = handler[name]
        if ws.client_state == WebSocketState.DISCONNECTED:
            del handler[name]
            return None
        else:
            return ws
    else:
        return None
