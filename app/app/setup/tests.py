from logging import getLogger

import httpx
from fastapi import FastAPI

from app.models.orm import Base, Entry, RegisteredActor
from app.services.service_worker import ServiceWorker
from app.util.data_import.data_importer import create_regular

logger = getLogger(__name__)


def clear_db(session):
    engine = session.bind.engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def run_app_tests(app: FastAPI, sw: ServiceWorker):
    logger.warning("TEST: RUN APP TESTS")
    test_template = sw.db_session.query(Entry).filter(Entry.slug == "test_template",Entry.language=="en").first()
    template = sw.template_codes.to_proper_model(test_template)
    admin = sw.db_session.query(RegisteredActor).filter(RegisteredActor.registered_name == "admin").first()
    entry = create_regular(template, sw, "admin")
    #sw.entry.process_entry_post(entry, admin)

    # httpx.get("http://localhost:8000/api/v1/slug/test_template",params={"language":"en"})


if __name__ == "__main__":
    resp = httpx.get("http://localhost:8100/api/v1/slug/test_template",params={"language":"en"})
    print(resp.status_code)