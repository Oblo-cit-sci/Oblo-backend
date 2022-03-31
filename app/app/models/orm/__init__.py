from sqlalchemy.ext.declarative import declared_attr, as_declarative


@as_declarative()
class Base(object):
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()


from app.models.orm.domain_meta import DomainMeta
from app.models.orm.domain_orm import Domain
from app.models.orm.actor_orm import *
from app.models.orm.registered_actor_orm import RegisteredActor
from app.models.orm.oauth_actor import OAuthActor
from app.models.orm.token import Token

from app.models.orm.tag_orm import Tag
from app.models.orm.entry_orm import Entry


from app.models.orm.relationships import (
    ActorEntryAssociation,
    EntryTagAssociation,
    EntryTranslation,
    EntryEntryAssociation,
)
