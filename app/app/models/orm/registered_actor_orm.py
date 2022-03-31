from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref, relationship, deferred

from app.models.orm import Actor
from app.util.consts import ADMIN, EDITOR, USER, EDITOR_CONFIG, VISITOR


class RegisteredActor(Actor):
    id = Column(Integer, ForeignKey("actor.id"), primary_key=True)
    registered_name = Column(String(64), index=True, unique=True)  # TO FILL
    email = Column(String, nullable=True)  # TO FILL
    email_validated = Column(Boolean, nullable=False, default=False)
    hashed_password = deferred(Column(String))  # TO FILL
    public_name = Column(String(32))  # TO FILL # -> Actor
    description = Column(Text, default="")  # -> Actor
    account_deactivated = Column(Boolean, default=False, nullable=False)

    global_role = Column(String(32), default=USER)  # -> Actor

    # profile_image = Column(LargeBinary)
    # profile_avatar = Column(LargeBinary)

    # todo add: , cascade="save-update, merge, delete"
    token = relationship("Token", back_populates="actor", cascade="all, delete-orphan")

    entries = relationship(
        "ActorEntryAssociation", backref=backref("actor", lazy="select")
    )

    location = Column(JSONB)
    settings = Column(JSONB, default={})
    configs = Column(JSONB, default={})

    creation_date = Column(DateTime, default=datetime.now)

    # interested_topics = relationship("Tag", secondary="actortagassociation")

    __mapper_args__ = {"polymorphic_identity": "user"}

    @hybrid_property
    def is_visitor(self):
        return self.global_role == VISITOR

    @hybrid_property
    def is_editor(self):
        return self.global_role in [EDITOR, ADMIN]

    def is_editor_for_entry(self, entry):
        return (
            self.global_role == EDITOR
            and entry.domain in self.configs["editor"]["domain"]
        )

    def is_editor_for(self, domain_name: str, language: str):
        return (
            self.global_role == EDITOR
            and domain_name in self.editor_config["domain"]
            and language in self.editor_config["language"]
        )

    def p_is_admin(self):
        return self.global_role == ADMIN

    def editor_for_or_admin(self, domain_name: str, language: str):
        return self.is_editor_for(domain_name, language) or self.p_is_admin()

    @hybrid_property
    def is_admin(self):
        return self.global_role == ADMIN

    @hybrid_property
    def editor_config(self):
        return self.configs.get(EDITOR_CONFIG, {})

    # @hybrid_method
    # def editor_for_domain(cls, domain):
    #     return and_(cls.configs.has_key(EDITOR_CONFIG), cls.configs[(EDITOR_CONFIG, "domain")].cast(JSON).contains(domain))

    def __repr__(self):
        return f"User: {self.registered_name}"
