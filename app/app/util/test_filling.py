from app.models.orm import RegisteredActor
from app.util.consts import USER
from app.util.passwords import create_hash


def add_dummy_actors(session, num):
    for i in range(1, num + 1):
        n = "dummy" + str(i)
        exists = (
            session.query(RegisteredActor)
            .filter(RegisteredActor.registered_name == n)
            .one_or_none()
        )
        if not exists:
            # noinspection PyArgumentList
            dummy = RegisteredActor(
                registered_name=n,
                email=n + "@uab.cat",
                public_name=n,
                hashed_password=create_hash(n),
                global_role=USER,
            )
            session.add(dummy)
