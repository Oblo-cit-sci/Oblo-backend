import os
from logging import getLogger, Filter, DEBUG, INFO
from logging.config import dictConfig

import yaml
from yaml import Loader

from app.settings import LOG_BASE_DIR, CONFIG_FILE_PATH

root_logger = getLogger()
root_logger.setLevel(DEBUG)


class InfoFilter(Filter):
    def filter(self, rec):
        return rec.levelno == INFO


logger_levels = {}


def init():
    global logger_levels

    if not os.path.isdir(LOG_BASE_DIR):
        os.makedirs(LOG_BASE_DIR)

    def rec_set_logger(log_config, module_name=None) -> dict:
        result = {}
        if type(log_config) == str:
            result[module_name] = {"level": log_config}
        else:
            if module_name:
                result[module_name] = {
                    k: v for k, v in log_config.items() if k != "_sub"
                }
            for module, level_and_children in log_config.get("_sub", {}).items():
                full_module_name = module_name + "." + module if module_name else module
                rec_results = rec_set_logger(level_and_children, full_module_name)
                result = {**result, **rec_results}
        return result

    if not os.path.isfile(CONFIG_FILE_PATH):
        root_logger.warning(f"Could not find loglevel config: {CONFIG_FILE_PATH}")
        return

    config_file_path = CONFIG_FILE_PATH
    orig_log__config = yaml.load(open(config_file_path), Loader)
    root_logger.debug("logger config", orig_log__config)

    log_config = {**orig_log__config, "loggers": {}}
    for path in orig_log__config["loggers"]:
        log_config["loggers"].update(
            rec_set_logger(orig_log__config["loggers"][path], path)
        )

    try:
        dictConfig(log_config)
        logger_levels = log_config["loggers"]
        if days_info_handler := list(
            filter(lambda h: h.name == "days_handler", getLogger("app").handlers)
        ):
            days_info_handler[0].addFilter(InfoFilter())

    except ValueError as err:
        root_logger.exception(err)
        root_logger.error("Cannot configure logger")

if not logger_levels:
    init()

def get_logger(name):
    logger = getLogger(name)
    if name not in logger_levels:
        dirs = name.split(".")
        for i in range(len(dirs)):
            parent = ".".join(dirs[:-i])
            if parent in logger_levels:
                root_logger.warning(f"logger {name} level not found. Using logger of '{parent}'")
                return getLogger(parent)
        root_logger.warning(f"logger {name} level not found. Setting level to DEBUG")
        logger.setLevel("DEBUG")
    else:
        return logger
