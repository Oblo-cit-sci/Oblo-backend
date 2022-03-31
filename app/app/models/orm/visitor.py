from sqlalchemy import Column, ForeignKey, Integer, String

from app.models.orm import Actor


# NOT IN USE ATM, DID NOT WORK...
class Visitor(Actor):
    __tablename__ = "visitor"
    id = Column(Integer, ForeignKey("actor.id"), primary_key=True)
    registered_name = Column(
        String(32), index=True, unique=True, default="visitor"
    )  # TO FILL

    __mapper_args__ = {"polymorphic_identity": "visitor"}

    def __repr__(self):
        return "Visitor"
