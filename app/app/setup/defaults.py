from logging import getLogger
from os.path import join
from typing import List

from jsonschema import ValidationError
from sqlalchemy.orm import Session

from app.models.orm import RegisteredActor
from app.services import schemas
from app.services.schemas import user_settings_schema_file
from app.settings import COMMON_DATA_FOLDER
from app.util.dict_rearrange import update_strict
from app.util.files import read_orjson, JSONPath

logger = getLogger(__name__)



def fix_defaults(session: Session):
    """
    this is not used atm. the schemas which are used to validate the settings are not on the main branch
    """
    # user_settings_defaults(session)
    pass


def user_settings_defaults(session: Session):
    users: List[RegisteredActor] = session.query(RegisteredActor).all()
    default_settings = read_orjson(
        join(COMMON_DATA_FOLDER, "user_settings_default.json")
    )

    for user in users:
        try_default_values = False
        try:
            schemas.validate(user_settings_schema_file, user.settings)

        except ValidationError:
            try_default_values = True

        if try_default_values:
            try:
                settings = {**user.settings}
                schemas.default_validate(user_settings_schema_file, settings)
                user.settings = settings
            except ValidationError as exc:
                msg = f"WHY NO LOG?! User has invalid settings. go and fix em manually. username: {user.registered_name}. Fixing default settings\nmessage:{exc.message}"
                print(msg)
                new_settings = {**default_settings}
                update_strict(new_settings, user.settings)
                user.settings = new_settings
    session.commit()



