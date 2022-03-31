from logging import getLogger
from typing import List

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import backref, relationship

from app.models import orm
from app.settings import env_settings

logger = getLogger(__name__)


class ActorEntryAssociation(orm.Base):
    actor_id = Column(Integer, ForeignKey("actor.id"), primary_key=True)
    entry_id = Column(Integer, ForeignKey("entry.id"), primary_key=True)
    role = Column(String)

    def __init__(self, actor_id: int, role: str):
        self.actor_id = actor_id
        self.role = role

    def __repr__(self):
        if not env_settings().is_dev():
            logger.warning(
                f"Calling {self.__class__.__name__} __repr__ might cause additional select queries"
            )
        return "entry actor: %s: %s:%s  " % (
            self.entry.title[:40] + "..."
            if len(self.entry.title) > 40
            else self.entry.title,
            self.actor.registered_name,
            self.role,
        )

    def csv_format(self, sep: str):
        return self.actor.registered_name + sep + self.role


class EntryTagAssociation(orm.Base):
    entry_id = Column(Integer, ForeignKey("entry.id"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tag.id"), primary_key=True)

    entry = relationship(orm.Entry, back_populates="tags")
    tag = relationship(orm.Tag, backref=backref("entries_tag"))

    group_name = Column(String, nullable=True)
    config = Column(JSONB)

    def __init__(self, tag: orm.Tag, group_name: str):
        self.tag = tag
        self.group_name = group_name

    def __repr__(self):
        if not env_settings().is_dev():
            logger.warning(
                f"Calling {self.__class__.__name__} __repr__ might cause additional select queries"
            )
        return "entry tag: %s -> %s " % (
            self.entry.title[:40] + "..."
            if len(self.entry.title) > 40
            else self.entry.title,
            self.tag.value,
        )


class EntryEntryAssociation(orm.Base):
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("entry.id"))
    destination_id = Column(Integer, ForeignKey("entry.id"))
    source = relationship(orm.Entry, foreign_keys=[source_id])
    destination = relationship(orm.Entry, foreign_keys=[destination_id])
    # maybe also primary_key=True, if there could be multiple types of links between 2 entries
    # reference_type = Column(String, index=True, nullable=True)
    reference = Column(JSONB, nullable=True, default={})

    def __init__(self, source: orm.Entry, destination: orm.Entry, reference: dict):
        self.source = source
        self.destination = destination
        self.reference = reference

    def __repr__(self):
        return (
            f"Entry-Entry ref: {self.source.id}/{self.source.slug} -> "
            f"{self.destination.id}/{self.destination.slug}: {self.reference}"
        )


class EntryTranslation(orm.Base):
    id = Column(Integer, primary_key=True)
    entries = relationship("Entry", back_populates="translation_group")

    # we should have this so that no issue is raised
    def __init__(self, entries: List[orm.Entry]):
        self.entries = entries


# class ActorTagAssociation(orm.Base):
#     actor_id = Column(Integer, ForeignKey("actor.id"), primary_key=True)
#     tag_id = Column(Integer, ForeignKey("tag.id"), primary_key=True)
#
#     def __repr__(self):
#         if not env_settings().is_dev():
#             logger.warning(
#                 f"Calling {self.__class__.__name__} __repr__ might cause additional select queries"
#             )
#         return "actor tag: %s: %s  " % (
#             self.entry.title[:40] + "..."
#             if len(self.entry.title) > 40
#             else self.entry.title,
#             self.actor.registered_name,
#         )
