from sqlalchemy import Column, Integer, String

from app.models.orm import Base


class Actor(Base):
    id = Column(Integer, primary_key=True)
    type = Column(String(16))

    __mapper_args__ = {"polymorphic_identity": "actor", "polymorphic_on": type}
