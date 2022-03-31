from sqlalchemy import Column, String, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship

from app.models.orm import Base


class DomainMeta(Base):
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)
    content = Column(JSONB, nullable=False)
    index = Column(Integer, autoincrement=True, nullable=False)  # was unique before
    is_active = Column(Boolean, nullable=False, default=True)
    default_language = Column(String, nullable=False)

    language_domain_data = relationship(
        "Domain", back_populates="domainmeta", cascade="all, delete-orphan"
    )
    languages = association_proxy("language_domain_data", "language")

    # @property will trigger queries each time...?
    def get_active_languages(self):
        return list(
            map(
                lambda lang_domain: lang_domain.language,
                filter(
                    lambda lang_domain: lang_domain.is_active, self.language_domain_data
                ),
            )
        )

    def __repr__(self):
        return f"Domainmeta: {self.name}"
