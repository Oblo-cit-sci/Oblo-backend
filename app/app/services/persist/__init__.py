from typing import Any


class PersistService:
    def __init__(self, db_session: Any):
        self.db_session = db_session
