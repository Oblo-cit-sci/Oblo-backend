from datetime import datetime
from logging import getLogger
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, Integer, String, Text, cast, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, BYTEA
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import Comparator, hybrid_method, hybrid_property
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.types import DateTime
from starlette.status import HTTP_403_FORBIDDEN

from app.models.orm import Base, RegisteredActor
from app.settings import env_settings
from app.util.consts import (
    ADMIN,
    CREATOR,
    NO_DOMAIN,
    PRIVATE,
    PUBLIC,
    PUBLISHED,
    DOMAIN,
    CONTENT,
    STATUS,
    OWNER,
    REVIEWER,
    READ_ACCESS,
    COLLABORATOR,
    EDITOR,
    REQUIRES_REVIEW,
    REGULAR,
    LANGUAGE,
)

logger = getLogger(__name__)


class CastingArray(ARRAY):
    def bind_expression(self, bindvalue):
        return cast(bindvalue, self)


class TemplateComparator(Comparator):
    def reverse_operate(self, op, other, **kwargs):
        pass

    def operate(self, op, *other, **kwargs):
        pass

    def __eq__(self, slug):
        return self == slug


def get_entry_default_value(key):
    if key == DOMAIN:
        return NO_DOMAIN
    elif key == "status":
        return PUBLISHED
    elif key == "privacy":
        return PUBLIC
    elif key == "license":
        return "CC0"
    elif key == "language":
        return env_settings().DEFAULT_LANGUAGE
    elif key == "description":
        return ""


class Entry(Base):
    id = Column(Integer, autoincrement=True, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, default=uuid4)
    type = Column(String(63), nullable=False)
    creation_ts = Column(DateTime, default=datetime.now)
    domain = Column(String, nullable=True, default=get_entry_default_value(DOMAIN))

    template_id = Column(Integer, ForeignKey("entry.id"), nullable=True)
    template = relationship("Entry", remote_side=[id])
    template_version = Column(Integer, nullable=True)  # todo shoulg go!

    aspects = deferred(Column(CastingArray(JSONB), default=[]), group=CONTENT)
    values = deferred(Column(JSONB, default={}), group=CONTENT)
    rules = deferred(Column(JSONB, default={}), group=CONTENT)
    config = Column(JSONB, default={})

    last_edit_ts = Column(DateTime, default=datetime.now)
    version = Column(Integer, nullable=False, default=1)
    slug = Column(String(255), index=True, nullable=True)
    title = Column(String(255), nullable=True, default="")
    status = Column(String(31), default=get_entry_default_value(STATUS))
    description = Column(Text, nullable=True, default="")
    language = Column(String, index=True, default=get_entry_default_value("languages"))
    privacy = Column(String(31), default=get_entry_default_value("privacy"))
    license = Column(String(31), default=get_entry_default_value("license"))
    image = Column(String(125), nullable=True)
    attached_files = Column(CastingArray(JSONB), default=[])
    location = Column(CastingArray(JSONB), nullable=True) # deprecated but still heavily used. USE "geojson_location"
    geojson_location = Column(JSONB, nullable=True)

    #
    translation_id = Column(Integer, ForeignKey("entrytranslation.id"))
    translation_group = relationship("EntryTranslation", back_populates="entries")
    translations = association_proxy("translation_group", "entries")
    changes = deferred(Column(ARRAY(BYTEA), nullable=True))

    #
    __table_args__ = (UniqueConstraint("slug", "language"),)

    tags = relationship(
        "EntryTagAssociation",
        back_populates="entry",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    entry_tags = association_proxy("tags", "tag")

    # TODO DOES THIS DELETE THE ENTRY WHEN THE RELATIONSHIP IS REMOVED???
    actors = relationship(
        "ActorEntryAssociation",
        backref="entry",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    entry_refs = relationship(
        "EntryEntryAssociation",
        foreign_keys="[EntryEntryAssociation.source_id]",
        cascade="all, delete-orphan",
        back_populates="source",
    )

    # todo: test if this works
    # CheckConstraint('(version - 1)  == cardinality(changes)', name='check_changes_length')

    # todo has_read_access / write_access names match not behaviour

    def protected_read_access(self, actor: RegisteredActor, raise_error: bool = False):
        # print("check private read access", actor, self.actors)
        # todo remove 1. condition, when actor is always at least "visitor"-
        # till then conditions cannot be merged, or it will crash
        try:
            if not actor:
                return False
            if actor.is_visitor:
                return False
            for actor_rel in self.actors:
                if (
                    actor_rel.role in [CREATOR, READ_ACCESS]
                    and actor_rel.actor.id == actor.id
                ):
                    return True
            if raise_error:
                raise HTTPException(HTTP_403_FORBIDDEN)
            return False
        except Exception as err:
            logger.error(f"protected_read_access error for entry(id): {self.id}")
            logger.exception(err)

            return False

    @hybrid_method
    def has_read_access(self, actor: RegisteredActor, raise_error: bool = False):
        if self.status == PUBLISHED and self.privacy == PUBLIC:
            return True
        if not actor:
            raise HTTPException(HTTP_403_FORBIDDEN)
        if actor.global_role == ADMIN:
            return True
        if actor.global_role == EDITOR:
            editor_config = actor.configs[EDITOR]
            if (
                self.domain in editor_config[DOMAIN]
                and self.language in editor_config[LANGUAGE]
            ):
                return True
        for actor_rel in self.actors:
            # todo not shared
            if actor_rel.actor.id == actor.id:
                return True
        if raise_error:
            raise HTTPException(HTTP_403_FORBIDDEN)
        return False

    @hybrid_method
    def has_write_access(self, actor: RegisteredActor):
        if actor:
            if actor.global_role == ADMIN:
                return True
            elif self.status == REQUIRES_REVIEW and actor.global_role == EDITOR:
                editor_config = actor.configs[EDITOR]
                if (
                    self.domain in editor_config[DOMAIN]
                    and self.language in editor_config[LANGUAGE]
                ):
                    return True
            else:
                for actor_rel in self.actors:
                    if actor_rel.actor.id == actor.id and actor_rel.role in [
                        CREATOR,
                        OWNER,
                        COLLABORATOR,
                        REVIEWER,
                    ]:
                        return True
        return False

    @hybrid_property
    def private(self):
        return self.privacy == PRIVATE

    @hybrid_property
    def public(self):
        return self.privacy == PUBLIC

    @hybrid_property
    def template_slug(self):
        if not self.template:
            return False
        else:
            return self.template.slug

    # todo. damn how?!?
    # @template_slug.expression
    # def template_slug(cls):
    # 	entry_template = aliased(Entry)
    # 	return Entry.template.slug

    @hybrid_property
    def creator(self):
        return next(filter(lambda e_role: e_role.role == CREATOR, self.actors)).actor

    # not used atm
    @hybrid_method
    def is_creator(self, user: RegisteredActor):
        return (
            next(filter(lambda e_role: e_role.role == CREATOR, self.actors)).actor
            == user
        )

    # # TODO does not work yet
    # # noinspection Mypy
    # @is_creator.expression
    # def is_creator(cls, user: RegisteredActor):
    #     return (select([
    #                       case([(exists().where(
    #                           and_("ActorEntryAssociation.actor_id" == user.id,
    #                                "ActorEntryAssociation.role" == CREATOR, )).correlate(
    #                           cls), True)], else_=False, ).label("ee")]).label("fsfsf"))

    def __repr__(self):
        if self.type == REGULAR:
            return f"Entry:{self.title} ({self.language})"
        else:
            return f"Entry:{self.slug}/{lang if (lang := self.language) else 'NO-LANG'}"


# __mapper_args__ = {"version_id_col": version}
