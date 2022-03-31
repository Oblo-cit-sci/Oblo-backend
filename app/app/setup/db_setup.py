import sys
from logging import getLogger

from pydantic import ValidationError

from app.models.orm import RegisteredActor
from app.models.schema.actor import ActorRegisterIn
from app.services.service_worker import ServiceWorker
from app.settings import env_settings, COMMON_DATA_FOLDER
from app.util.consts import ADMIN, USER, VISITOR
from app.util.files import JSONPath

logger = getLogger(__name__)


def setup_default_actors(sw: ServiceWorker) -> RegisteredActor:
    """
    returns the admin account
    """
    admin = sw.actor.crud_read(ADMIN, raise_error=False)

    if not admin:
        logger.info(f"No actor: admin. creating...")
        try:
            validated_admin = ActorRegisterIn(
                registered_name=ADMIN,
                email=env_settings().FIRST_ADMIN_EMAIL,
                password=env_settings().FIRST_ADMIN_PASSWORD.get_secret_value(),
                password_confirm=env_settings().FIRST_ADMIN_PASSWORD.get_secret_value(),
                settings={},
            )
        except ValidationError:
            logger.exception("First admin userdata not valid. Bye")
            logger.warning(
                f"{env_settings().FIRST_ADMIN_EMAIL}, {env_settings().FIRST_ADMIN_PASSWORD}"
            )
            sys.exit(0)

        try:
            JSONPath(COMMON_DATA_FOLDER, "user_settings_default.json")
        except FileNotFoundError as err:
            logger.error(err)
            exit(1)
        admin = sw.actor.crud_create(validated_admin, global_role=ADMIN, email_validated=True)

    visitor = sw.actor.crud_read(VISITOR, False)
    if not visitor:
        # noinspection PyArgumentList
        sw.db_session.add(
            RegisteredActor(
                registered_name="visitor",
                public_name="visitor",
                global_role=USER,
                email_validated=True,
            )
        )
        sw.db_session.commit()

    return admin
