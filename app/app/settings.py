import json
import os
import sys
from functools import lru_cache
from logging import getLogger
from os import listdir
from os.path import join
from pathlib import Path
from typing import Literal, Optional, Set

from colorama import Fore
from pydantic import (
    BaseSettings,
    EmailStr,
    SecretStr,
    Extra,
    Field,
    ValidationError,
    HttpUrl,
    AnyHttpUrl,
)
from pydantic.env_settings import read_env_file

from app.util.consts import DEV, PROD, TEST

BASE_DIR = Path(__file__).parent.parent.absolute().as_posix()
if "main.py" not in listdir(BASE_DIR):
    raise Exception(
        "basedir of project does not contain main.py (is the settings still in the app folder?"
    )

L_MESSAGE_COMPONENT = Literal["be", "fe"]

# TABLES
BACKEND_MESSAGE_COMPONENT = "be"
FRONTEND_MESSAGE_COMPONENT = "fe"
MESSAGES_LANGUAGES = "languages"
MESSAGES_STATUSES = "status"
MESSAGES_CHANGES = "changes"

L_MESSAGE_TABLES = [BACKEND_MESSAGE_COMPONENT, FRONTEND_MESSAGE_COMPONENT]
logger = getLogger(__name__)

# make sure that it exists (cuz the filehandlers use them)
CONFIG_DIR = join(BASE_DIR, "configs")


def get_env_file(env_: str) -> str:
    return join(CONFIG_DIR, f".{env_}.env")


env = os.environ.get("ENV")
if env:
    env_file = get_env_file(env)
else:
    print(Fore.RED + "ENV parameter not set. checking 'prod'")
    env = PROD
    env_file = get_env_file(env)
    if not os.path.isfile(env_file):
        print(Fore.RED + f"file not found: {env_file}. Trying 'dev'..." + Fore.RESET)
        env = DEV
        env_file = get_env_file(env)

if env not in [DEV, PROD, TEST]:
    raise Exception(f"unknown env: {env}. Should be one of: {[DEV, PROD, TEST]}")

if not os.path.isfile(env_file):
    print(f"env file not found: {env_file}.\nCreate that file and run again")
    print(os.path.abspath(env_file))
    sys.exit(1)

if env != os.environ.get("ENV"):
    os.environ["ENV"] = env

print(Fore.GREEN + f"Using env: {env}", Fore.RESET)
logger.info(f"{env} -> {env_file}")


class Settings(BaseSettings):
    ENV: str
    HOST: AnyHttpUrl = Field(
        "http://0.0.0.0", description="Host address(including port) of the frontend app"
    )
    POSTGRES_HOST: str = Field(
        ..., description="hostname of the postgres (e.g. localhost)"
    )  # should be opentek_db
    POSTGRES_USER: str = Field(..., description="username for postgres")
    POSTGRES_PASSWORD: SecretStr = Field(
        ..., description="password to the postgres database"
    )
    POSTGRES_DB: str = Field(..., description="name of the database")

    FIRST_ADMIN_EMAIL: str = Field(
        ..., description="email address of the 1. admin user"
    )
    FIRST_ADMIN_PASSWORD: SecretStr = Field(
        ..., description="Password for the 1. admin user"
    )

    EMAIL_ENABLED: bool = Field(False, description="Set if emails should be sent")
    EMAIL_SENDER: EmailStr = None
    EMAIL_ACCOUNT: EmailStr = None
    EMAIL_PWD: SecretStr = ""
    EMAIL_SSL_SERVER: str = ""

    SESSION_SECRET: SecretStr

    MAP_DEFAULT_MAP_STYLE: str
    MAP_ACCESS_TOKEN: SecretStr
    ADDITIONAL_MAP_STYLES: Optional[Set[str]] = Field([], description="Additional map styles")

    PLATFORM_TITLE: str = Field(
        "Oblo",
        description="The title of the platform. Visible on the appbar, when no-domain",
    )

    BASE_ROUTER_PREFIX = Field("/api", description="Api endpoint base router prefix")

    APP_DIR: str = Field("fe", description="The directory where the frontend-app is located, relatively to the the app path")
    APP_ROUTE: str = Field("/", description="Application path the frontend app is hooked to")

    BASE_DATA_FOLDER: str = Field("data",description="Base data folder, where application files are stored")
    INIT_DOMAINS_SUBPATH: str = Field("domains",description="Subpath to the folder where the initial domains are stored")

    LANGUAGE_SQLITE_FILE_PATH: str = "messages.sqlite"

    DEFAULT_LANGUAGE: str = "en"

    INIT_DOMAINS: bool = True
    INIT_TEMPLATES_CODES: bool = True

    INIT_LANGUAGE_TABLES: bool = True
    REPLACE_MESSAGES: bool = False
    DEACTIVATE_LANGUAGES: Optional[Set[str]] = Field([], description="languages that should be deactivated")

    LOGIN_REQUIRED: bool = False
    EMAIL_VERIFICATION_REQUIRED: bool = True

    DEFAULT_USER_GUIDE_URL: Optional[HttpUrl] = Field(
        None, description="URL to the external user guides"
    )

    TIMING_MIDDLEWARE_ACTIVE: bool = False

    DATA_MIGRATION: bool = False
    RUN_APP_TESTS: bool = False

    LANGUAGE_LIST_SOURCE_REPO_URL: HttpUrl = "https://github.com/umpirsky/language-list"

    MIGRATION_HELP_ACTIVE: Optional[bool] = Field(False,
                                                  description="change some config helping and adaptations "
                                                              "to the init code for migration")

    # todo currently not in the default .env. doesnt work properly... all origins seem allowed.
    CORS_OTHER_ORIGINS: Optional[str] = ""

    # FOR DEV. todo test if still usable. not in .env
    MODEL_CONFIG_EXTRA = Extra.forbid  # if ENV == DEV else Extra.ignore

    DEFAULT_LANGUAGE_FE_MESSAGES_FILE: Optional[str] = Field(
        None,
        description="A frontend messages.json file that is stored"
                    " in the frontend development repo (works only in dev env)",
    )

    RESET_TEST_DB: bool = False  # only works in test env

    class Config:
        env_file = env_file

    def is_dev(self):
        # test should be like production. maybe one called debug.
        return self.ENV in [DEV, TEST]


@lru_cache()
def env_settings():
    try:
        return Settings()
    except ValidationError as err:
        logger.exception(err)
        missing_fields = [e.loc_tuple() for e in err.raw_errors]
        for field in missing_fields:
            field_name = field[0]
            logger.error(
                f"{field_name}: {Settings.__fields__[field_name].field_info.description}"
            )
        raise


def settings_check():
    print("Variable unset/defaults:")
    print(json.dumps(check_unset_settings(), indent=2))
    check_redundant_settings_fields()


def check_unset_settings():
    unset = [
        f
        for f in env_settings().__fields__
        if f not in env_settings().dict(exclude_unset=True)
    ]
    # unset.remove("model_config_extra")
    defaults = {}
    for field in unset:
        defaults[field] = env_settings().__fields__[field].get_default()
    return defaults


def check_redundant_settings_fields():
    env_variables = read_env_file(Settings.__config__.env_file, case_sensitive=True)
    for variable in env_variables:
        if variable not in Settings.__fields__:
            logger.warning(f"Redundant env variable: {variable}")


BASE_DATA_FOLDER = join(BASE_DIR, env_settings().BASE_DATA_FOLDER)

INIT_DATA_FOLDER = join(BASE_DATA_FOLDER, "init_data")
USER_DATA_FOLDER = join(BASE_DATA_FOLDER, "user_data")
ENTRY_DATA_FOLDER = join(BASE_DATA_FOLDER, "entries_data")
COMMON_DATA_FOLDER = join(INIT_DATA_FOLDER, "common")
SCHEMA_FOLDER = join(BASE_DATA_FOLDER, "schemas")
BASE_LANGUAGE_DIR = join(INIT_DATA_FOLDER, "languages")
# @ deprecated. sett setup/init_data/init_message_tables.setup_messages_db
BASE_MESSAGES_DIR = join(BASE_DATA_FOLDER, "messages")
INIT_DOMAINS_FOLDER = join(
    INIT_DATA_FOLDER, env_settings().INIT_DOMAINS_SUBPATH
)  # os.path.join(INIT_DATA_FOLDER, "domains")
MESSAGES_DB_PATH = join(BASE_DATA_FOLDER, env_settings().LANGUAGE_SQLITE_FILE_PATH)
# should be assets folder, includes these and e.g. in case of licci, map images
TEMP_FOLDER = join(BASE_DATA_FOLDER, "temp")
TEMP_APP_FILES = join(BASE_DATA_FOLDER, "temp_files")

# todo move into data folder
BASE_STATIC_FOLDER = join(BASE_DIR, "static")
DOMAINS_IMAGE_FOLDER = join(BASE_STATIC_FOLDER, "images", "domains")
JS_PLUGIN_FOLDER = join(BASE_STATIC_FOLDER, "js")

CONFIGS_PATH = join(BASE_DIR, "configs")
CONFIG_FILE_PATH = join(CONFIGS_PATH, "logger_config.yml")

LOG_BASE_DIR = join(BASE_DIR, "logs")
