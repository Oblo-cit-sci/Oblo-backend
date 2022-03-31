from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models import orm
from app.models.orm import Base
from app.util.passwords import generate_access_token


def create_expiration_date():
    return datetime.now() + timedelta(days=7)


def default_token_type():
    return "bearer"


class Token(Base):
    id = Column(Integer, primary_key=True)
    access_token = Column(String, default=generate_access_token, nullable=False)
    refresh_token = Column(String, default=generate_access_token, nullable=False)
    token_type = Column(String, default=default_token_type)
    actor_id = Column(Integer, ForeignKey("actor.id"))
    actor = relationship("RegisteredActor", back_populates="token")
    expiration_date = Column(DateTime, default=create_expiration_date)
    # user_agent = Column(String)

    def __init__(self, actor: orm.RegisteredActor):
        self.actor = actor

    def update(self):
        self.access_token = generate_access_token()
        self.refresh_token = generate_access_token()
        self.expiration_date = create_expiration_date()
