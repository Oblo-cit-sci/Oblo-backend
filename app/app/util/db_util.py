from logging import getLogger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.setup_db import Session as DBSession

logger = getLogger(__name__)


def commit_and_new(session: Session = None) -> Session:
    if session:
        logger.debug("commit session")
        try:
            if session.new:
                logger.debug("new:\n%s" % "\n".join(repr(e) for e in session.new))
            if session.dirty:
                logger.debug("changed:\n%s" % "\n".join(repr(e) for e in session.dirty))
            session.commit()
        except IntegrityError as err:
            logger.warning(err.args[0])
            logger.warning("new: %s" % "\n".join(repr(e) for e in session.new))
            logger.warning("rollback!!")
            session.rollback()
        return session
    else:
        logger.debug("new session")
        return DBSession()
