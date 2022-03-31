import inspect
import sys
from glob import glob
from logging import getLogger
from os.path import basename, dirname, join

from app.globals import available_plugins, registered_plugins
from app.settings import INIT_DOMAINS_FOLDER
from app.util.plugins import BasePlugin, activate_plugin, AvailablePlugin

logger = getLogger(__name__)


def init_plugin_import(domain):
    plugin_files = glob(join(INIT_DOMAINS_FOLDER, domain, "plugins/*.py"))
    for plugin_path in plugin_files:
        plugin_filename = basename(plugin_path)
        logger.debug(f"plugin file: {plugin_filename}")
        # todo, maybe this can go out of the loop up
        parent_dir = dirname(plugin_path)
        sys.path.insert(0, parent_dir)
        try:
            plugin = __import__(basename(plugin_path)[:-3])
        except ModuleNotFoundError as mnfe:
            logger.warning(
                f"Cannot import plugin module: {basename(plugin_path)}. reason: {mnfe}"
            )
            continue
        for clazz in inspect.getmembers(plugin, inspect.isclass):
            if not issubclass(clazz[1], BasePlugin) or clazz[1] == BasePlugin:
                continue
            clazz_dir = dir(clazz[1])
            if "plugin_name" not in clazz_dir:
                logger.warning(f"Plugin does not have a name {clazz.__name__}")
                continue
            plugin_name = getattr(clazz[1], "plugin_name", None)
            if "__call__" not in clazz_dir:
                logger.warning(f"plugin does not implement __call__: {plugin_name}")
                continue
            if plugin_name in registered_plugins:
                logger.warning(
                    f"duplicate plugin name: {plugin_name} of file {plugin_filename} already exists in {available_plugins[plugin_name].plugin_path}"
                )
                continue
            logger.debug(f"adding plugin '{plugin_name}' from file {plugin_filename}")
            available_plugins[plugin_name] = AvailablePlugin(*clazz, plugin_path)
            activate_plugin(plugin_name)
