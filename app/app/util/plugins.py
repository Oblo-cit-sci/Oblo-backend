from logging import getLogger
from os.path import basename
from typing import Dict, Optional, Tuple, TYPE_CHECKING
from collections import namedtuple
from app.globals import available_plugins, registered_plugins
from app.models.orm import RegisteredActor, Entry
from app.util.exceptions import ApplicationException

AvailablePlugin = namedtuple(
    "Available_plugins_struct", ["class_name", "clazz", "plugin_path"]
)

logger = getLogger(__name__)

if TYPE_CHECKING:
    pass


class BasePlugin:
    pass

    def get_current_actor(self, **kwargs) -> Optional[RegisteredActor]:
        actor: RegisteredActor = kwargs.get("current_actor")
        if not actor:
            msg = f"current_actor missing in kwargs for plugin {self.plugin_name}"
            if "raise_exception" in kwargs:
                raise ApplicationException(422, msg)
            logger.error(msg)
        return actor

    def get_current_entry(self, **kwargs) -> Optional[Entry]:
        entry: Entry = kwargs.get("current_entry")
        if not entry:
            msg = f"current_actor missing in kwargs for plugin {self.plugin_name}"
            if "raise_exception" in kwargs:
                raise ApplicationException(422, msg)
            logger.error(msg)
        return entry

    def get_current_actor_and_entry(self, **kwargs) -> Tuple[RegisteredActor, Entry]:
        return self.get_current_actor(**kwargs), self.get_current_entry(**kwargs)


def activate_plugin(plugin_name: str) -> bool:
    if plugin_name in registered_plugins:
        logger.warning(f"Plugin with name {plugin_name} already hooked up")
        return False

    plugin_clazz_name, plugin_clazz, plugin_path = available_plugins.get(plugin_name)
    try:
        logger.debug(f"creating plugin object {plugin_clazz_name}")
        plugin_obj = plugin_clazz()
        logger.info(f"hooked up plugin {plugin_name}")
        registered_plugins[plugin_name] = plugin_obj
        return True
    except Exception as err:
        logger.exception(
            f"cannot create plugin object: {basename(plugin_path)}. reason: {err}"
        )
        return False


def deactivate_plugin(plugin_name: str) -> bool:
    if plugin_name not in registered_plugins:
        return False
    del registered_plugins[plugin_name]
    logger.info("plugin deactivated")
    return True


def call_plugin(plugin_name: str, data: Dict) -> Optional[Dict]:
    if plugin_name in registered_plugins:
        try:
            return registered_plugins[plugin_name](data)
        except Exception as err:
            logger.exception(err)
            return None
    else:
        return None
