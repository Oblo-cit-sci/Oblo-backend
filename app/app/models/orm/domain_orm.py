from typing import List, TYPE_CHECKING

from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship, Session, Query

from app.models.orm import Base


if TYPE_CHECKING:
    from app.models.orm import Entry


class Domain(Base):
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    language = Column(String, nullable=False, index=True)
    content = Column(JSONB, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)

    domainmeta_id = Column(Integer, ForeignKey("domainmeta.id"), nullable=False)
    domainmeta = relationship("DomainMeta")

    domain_name = association_proxy("domainmeta", "name")

    __table_args__ = (UniqueConstraint("domainmeta_id", "language"),)

    def __repr__(self):
        return f"Domain: {self.title} ({self.language})"

    def to_model(self, model):
        return model.from_orm(self)

    @property
    def entries(self) -> List["Entry"]:
        return self.entries_q.all()

    @property
    def codes_templates(self) -> List["Entry"]:
        """
        @note used atm. since, we are directly querying entries directly in the ctrl
        @return:
        """
        # noinspection PyUnresolvedReferences
        return self.entries_q.filter(Entry.type.in_(["code", "template"])).all()

    @property
    def entries_q(self) -> Query:
        sess = Session.object_session(self)
        from app.models.orm import Entry

        return sess.query(Entry).filter(
            Entry.domain == self.domain_name, Entry.language == self.language
        )
