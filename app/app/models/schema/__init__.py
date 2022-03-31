from datetime import datetime
from typing import Optional, List, Dict, Union, Any, Literal, Type
from uuid import UUID

from pydantic import (
    BaseModel,
    constr,
    conint,
    AnyUrl,
    Field,
    UUID4,
    root_validator,
    validator,
    Extra,
    PrivateAttr,
)

from app.models import orm
from app.models.orm import Entry
from app.settings import env_settings
from app.util.consts import DRAFT, PUBLIC, ENTRY_TYPES_LITERAL


class InConfig:
    extra = "forbid" if env_settings().is_dev() else "allow"


class ActorBase(BaseModel):
    registered_name: str
    public_name: Optional[str] = ""  # is gone for deactivated accounts

    class Config:
        orm_mode = True


class EntryRef(BaseModel):
    # todo not so great, since it can be empty...
    # todo should also include version. actually:
    # or template = {uuid:...} | {slug, language, version}
    uuid: Optional[UUID]
    slug: Optional[str] = None  # actually constrained.
    language: Optional[str] = None
    version: Optional[int] = None
    outdated: Optional[bool]

    class Config:
        orm_mode = True
        extra = Extra.ignore


class TagData(BaseModel):
    value: str
    text: str
    description: Optional[str]
    parent_value: Optional[str]

    class Config:
        orm_mode = True


class AbstractEntry(BaseModel):
    domain: str
    type: ENTRY_TYPES_LITERAL
    slug: constr(max_length=255) = None
    language: Optional[constr(max_length=3)]  # not for base-... entries
    _entry: Optional[Entry] = PrivateAttr()

    class Config:
        orm_mode = True

    def get_db_entry(self):
        return self._entry

    # @root_validator(pre=True)
    # def assign_entry(cls, values):
    #     print("assign entry root validator")

class EntryMeta(AbstractEntry):
    """
    TODO should not be created directly to prevent accidentally exposing
    private location
    """

    uuid: UUID
    creation_ts: datetime
    template: Optional[EntryRef] = None
    template_version: Optional[int]
    last_edit_ts: Optional[datetime] = None
    version: conint(ge=0) = 0
    title: str
    status: constr(max_length=32) = DRAFT
    description: constr(max_length=1024) = ""

    privacy: constr(max_length=32) = PUBLIC
    license: str = "CC0"
    image: Optional[Union[AnyUrl, UUID4]]  # uri
    tags: Dict[str, List[str]] = {}
    location: Optional[List[Dict]]
    attached_files: Optional[List["FileAttachment"]] = []
    actors: List["EntryActorRelationOut"] = []

    class Config:
        orm_mode = True

    # todo not sure if this is used or effictive (not used, cuz FastAPI does some stuff too)
    # json_dumps = orjson.dumps

    # reshape from db structure: a list of tag_rels which have
    @validator("tags", pre=True)
    def restructure_tags(cls, value: List["EntryTag"]):
        new_struct: Dict = {}
        for v in value:
            new_struct.setdefault(v.group_name, []).append(v.tag.value)
        return new_struct

    @validator("template", pre=True)
    def template_val(cls, value: Optional[Union[orm.Entry, Any]]):

        if type(value) == orm.Entry or hasattr(value, "slug"):
            return value.slug
        elif type(value) == dict:
            return value["slug"]
        else:
            return None


class FileAttachment(BaseModel):
    file_uuid: UUID4
    file_loc: int
    type: str = ""


class EntryActorRelationOut(BaseModel):
    actor: ActorBase
    role: str

    class Config:
        orm_mode = True


class EntryTag(BaseModel):
    tag: TagData
    group_name: str

    class Config:
        orm_mode = True


EntryMeta.update_forward_refs()


class ActorEntryRelationOut(BaseModel):
    entry: EntryMeta
    role: str

    class Config:
        orm_mode = True


class LocationBase(BaseModel):
    coordinates: List[float] = Field(..., min_items=2, max_items=3)
    place: Optional[Dict[str, str]]


class SearchValueDefinition(BaseModel):
    """
    for entries-search
    """

    name: Literal[
        "before_ts",
        "actor",
        "template",
        "domain",
        "language",
        "status",
        "tags",
        "title",
        "allowed_template_version",
    ]
    value: Union[str, int, List[str]]
    # for inclusion queries. all definition of a group are connected with an OR
    # this is required for search query which needs an OR of tags and title
    search_group: Optional[str] = None

    @root_validator(pre=True)
    def meta(cls, values):
        if values.get("name") == "meta":
            assert "column" in values
        # if values.get("name") == "before_ts":
        #     assert "ts" in values
        return values

    class Config:
        extra = "allow"


# todo should be EntriesSearchQuery... maybe make a `search` module
class EntrySearchQueryIn(BaseModel):
    required: List[SearchValueDefinition] = []
    include: List[SearchValueDefinition] = []
    settings: Dict[
        str, Any
    ] = {}  # all_uuids: true (default: false) which is used by the map

    class Config(InConfig):
        schema_extra = {
            "example": {
                "required": [{"name": "template", "value": "local_observation"}]
            }
        }


# just using __root__ would be nice, but in the controller/service we then have to access __root_ instead of uuids,
# so no benefit
class UUIDList(BaseModel):
    uuids: List[UUID4]


class ActorSearchQuery(BaseModel):
    name: Optional[str]  # both registered_name and public name


class MapEntry(BaseModel):
    """
    TODO should not be created directly to prevent accidentally exposing
    private location
    """

    uuid: UUID
    # domain: str
    template: str
    title: str
    # tags: Dict[str, List[str]] = {}
    location: Optional[List[Dict]]
    geojson_location: Optional[Dict]
    status: str

    # languages: List[str] = ["en"]

    class Config:
        orm_mode = True

    # reshape from db structure: a list of tag_rels which have
    # @validator("tags", pre=True)
    # def restructure_tags(cls, value: List["EntryTag"]):
    #     new_struct: Dict = {}
    #     for v in value:
    #         new_struct.setdefault(v.group_name, []).append(v.tag.title)
    #     return new_struct

    @validator("template", pre=True)
    def template_slug(cls, value: Entry):
        return value.slug


def raw_text_items_validator(item: Union[str, dict]) -> dict:
    if isinstance(item, dict):
        return item
    else:
        return {"text": item}


from app.models.schema.entry_schemas import EntryOut
from app.models.schema.template_code_entry_schema import (
    TemplateBaseInit,
    TemplateMerge,
)

EntryMainModelTypes = Union[
    Type[EntryOut], Type[TemplateBaseInit], Type[TemplateMerge]
]

EntryMainModel = Union[EntryOut, TemplateBaseInit, TemplateMerge]
