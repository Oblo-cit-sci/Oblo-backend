from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship

from app.models.orm import Base


class Tag(Base):
    id = Column(Integer, primary_key=True)
    value = Column(String(64), index=True, nullable=False)
    text = Column(JSONB, nullable=False, default={})  # index=True,
    description = Column(JSONB, nullable=False, default={})
    # tag hierarchy
    parent_id = Column(Integer, ForeignKey("tag.id"), nullable=True)
    parent = relationship("Tag", remote_side=[id])

    # source_entry_id = Column(Integer, ForeignKey("entry.id"), nullable=True)
    # todo could also rather be the uuid of that particular entry. better for version checking
    source_slug = Column(String, index=True, nullable=False)

    additional = Column(JSONB, nullable=True)

    # actors_interested = relationship("ActorTagAssociation", lazy="select")

    # todo does not work properly. its also an EntryTagAssociation
    entries = association_proxy("entries_tag", "entry")

    # entries_rel = relationship("EntryTagAssociation", cascade="delete")

    __table_args__ = (UniqueConstraint("value", "source_slug"),)

    def __init__(self, value: str, text: dict, source_slug: str):
        self.value = value
        self.text = text
        self.source_slug = source_slug

    def __repr__(self):
        return f"Tag: {self.value}"

    def for_lang(self, language: str):
        d = {
            "value": self.value,
            "text": self.text.get(language, ""),
            "description": self.description.get(language),
        }
        if self.parent:
            d["parent_value"] = self.parent.value
        return d
