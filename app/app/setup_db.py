import sys
from logging import getLogger
from time import sleep

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import scoped_session, sessionmaker

from app.models.orm import Base
from app.settings import env_settings

logger = getLogger(__name__)


def setup_db():
    settings = env_settings()

    sec_uri = "postgresql+psycopg2://%s:%s@%s/%s" % (
        settings.POSTGRES_USER,
        settings.POSTGRES_PASSWORD,
        settings.POSTGRES_HOST,
        settings.POSTGRES_DB,
    )
    uri = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD.get_secret_value()}"
        f"@{settings.POSTGRES_HOST}/{settings.POSTGRES_DB}"
    )
    try:
        logger.info(sec_uri)
        engine = create_engine(uri)  # , pool_pre_ping=True)
        Base.metadata.create_all(engine)
        return engine
    except OperationalError as er:
        # logger.warning(err)
        logger.error("Cannot create DB engine. Bye")
        logger.error(sec_uri)
        logger.error(er)
        sys.exit(1)


max_tries = 3
tries = 0

try:
    Session = scoped_session(
        sessionmaker(autocommit=False, autoflush=False, bind=setup_db())
    )
    logger.info("db scoped_session bound to db")
except OperationalError as err:
    logger.error(err)
    tries += 1
    sleep(5)
    if tries == max_tries:
        print("max tries reached")
        sys.exit(1)
