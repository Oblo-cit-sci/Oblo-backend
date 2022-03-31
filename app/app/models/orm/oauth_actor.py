from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.orm import Actor


class OAuthActor(Actor):
    id = Column(Integer, ForeignKey("actor.id"), primary_key=True)
    username = Column(String, nullable=False)
    service = Column(String, nullable=False)
    access_token = Column(String)
    access_token_data = Column(JSONB)
    user_data = Column(JSONB)

    __table_args__ = (UniqueConstraint("username", "service"),)

    __mapper_args__ = {"polymorphic_identity": "oauth"}
