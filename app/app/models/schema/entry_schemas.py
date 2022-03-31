from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from typing import Literal
from uuid import UUID

import orjson
from pydantic import UUID4, AnyUrl, BaseModel, constr, validator, Field, Extra

from app.models.orm.relationships import EntryEntryAssociation
from app.models.schema import (
    EntryActorRelationOut,
    EntryMeta,
    EntryRef,
    FileAttachment,
    InConfig,
    AbstractEntry, EntrySearchQueryIn,
)
from app.models.schema import aspect_models

from app.models.schema.aspect_models import (
    ItemLang,
    ItemListLang,
    AspectLangUpdate,
)
from app.settings import env_settings
from app.util.consts import PUBLIC
from app.util.files import orjson_dumps


# todo name: not just Base
class AbstractEntryBase(AbstractEntry):
    uuid: Optional[UUID4]
    title: Optional[str]  # not for base-... entries
    template: Optional[EntryRef]
    template_version: int = None
    description: constr(max_length=1024) = ""
    privacy: Literal["public", "private"] = PUBLIC
    license: str = "CC0"
    image: Optional[Union[AnyUrl, UUID4]]  # uri


class EntryRegular(AbstractEntryBase):
    location: Optional[List[Dict]]
    # Optional[Union[List[LocationBase], Dict[str, Union[LocationBase, List[LocationBase]]]]]
    actors: List[EntryActorRelationOut] = []
    # beware of the change. we take the
    tags: Optional[Dict[str, List[str]]]

    aspects: List[Dict] = []
    entry_refs: List = []
    values: Dict = {}
    rules: Optional[Dict]
    attached_files: List[
        FileAttachment
    ] = []  # or actually a document model, which has, entry similar fields

    @validator("entry_refs", pre=True, always=True)
    def entry_refs_validator(cls, value, values):
        if isinstance(value, dict):
            result: List[EntryRefIn] = []
            for dest_uuid, type_ in value.items():
                result.append(
                    EntryRefIn(destination=values[UUID], reference_type=type_)
                )
            return result
        else:
            return value

    class Config():
        json_loads = orjson.loads
        json_dumps = orjson.dumps
        # json_encoders= dict(Dict, orjson.)

class EntryTagDB(BaseModel):
    tag: str
    group_name: str


class EntryRefIn(BaseModel):
    source: Optional[UUID4]
    destination: UUID4
    reference_type: str


class EntryApiUpdateIn(AbstractEntryBase):
    """
    the same as EntryIn but without defaults, so they will be skipped if not defined
    """

    location: Optional[List[Dict]]
    actors: List[EntryActorRelationOut] = []
    tags: Dict[str, List[str]] = None

    attached_files: List[
        FileAttachment
    ] = []  # or actually a document model, which has, entry similar fields
    #  or actually a document model, which has, entry similar fields

    aspects: List[Dict] = None
    values: Dict[str, Any] = None
    entry_refs: Dict[Union[UUID, str], str]
    rules: Optional[Dict] = {}

    class Config(InConfig):
        pass


class EntryReviewIn(EntryApiUpdateIn):
    status: str

    class Config(InConfig):
        pass


class EntryOut(EntryMeta):
    """
    TODO should not be created directly to prevent accidentally exposing
    private location and location aspects
    """

    aspects: List[Dict]
    values: Dict
    rules: Optional[Dict]
    entry_refs: Any  # actually a list of entry-refs ass

    @validator("entry_refs", pre=True)
    def entry_refs_(cls, value: List[EntryEntryAssociation]):
        result = []
        for eea in value:
            if isinstance(eea, EntryEntryAssociation):
                if eea.destination.slug is not None:
                    result.append({"dest_slug": eea.destination.slug, **eea.reference})
                else:
                    result.append({"dest_slug": eea.destination.uuid, **eea.reference})
            else:
                result.append(eea)
        return result

    class Config:
        orm_mode = True
        json_loads = orjson.loads
        json_dumps = orjson_dumps


class EntryFieldSelection(BaseModel):
    # can be extended by demand, this is used for getting locations of "own as role" entries for locationAspect
    location: bool = False


class PaginatedEntryList(BaseModel):
    count: int
    entries: List[Union[UUID, EntryMeta]]
    prev_offset: Optional[int]
    next_offset: Optional[int]
    ts: datetime
    all_uuids: Optional[List[UUID]]


class EntryOutSignature(AbstractEntry):
    version: int
    uuid: UUID4
    domain: str
    # todo boolean if in config or calculated
    path: Optional[str]
    id: AnyUrl = Field(env_settings().HOST, alias="$id")

    @validator("id")
    def make_json_schema_id(cls, v, values):
        return f"{v}/api/entry/{str(values['uuid'])}"

    class Config:
        orm_mode = True


class EntryLangOut(AbstractEntryBase):
    title: str
    description: Optional[str] = ""
    language: str
    aspects: Optional[List[aspect_models.AspectLangOut]]

    class Config:
        orm_mode = True


class EntryIdIn(BaseModel):
    slug: str
    language: Optional[str]


class EntryDeltaModel(BaseModel):
    """
    applied when a base-(code,template) is updated and stored to changes
    """

    title: Optional[str]
    description: Optional[str]
    values: Optional[dict]
    aspects: Optional[list]
    rules: Optional[dict]
    config: Optional[dict]
    timestamp: Optional[float]
    version: int

    class Config:
        orm_mode = True


class CodeValuesLang(BaseModel):
    root: Optional[ItemLang]
    levels: Optional[ItemListLang]
    list: Optional[ItemListLang]

    long_description: Optional[str]  # for some templates


class EntryPreDbRoleModel(BaseModel):
    role: str
    actor: "EntryActorModel"


class EntryActorModel(BaseModel):
    registered_name: str
    public_name: Optional[str]


class EntryLangUpdate(BaseModel):
    title: str = ""
    description: str = ""
    aspects: List["AspectLangUpdate"] = []
    values: Optional["CodeValuesUpdate"]


class CodeValuesUpdate(BaseModel):
    root: Optional[ItemLang]
    levels: Optional[ItemListLang]
    list: Optional[ItemListLang]

    #
    long_description: Optional[str]  # for some templates


class EntryAction(BaseModel):
    name: str
    type: str  # call_plugin
    properties: dict  # (plugin_name?: str


class EntriesDownloadConfig(BaseModel):
    entries_uuids: List[Any] = (),
    select_data: Literal["metadata", "complete"]
    search_query: EntrySearchQueryIn

    class Config:
        extra = Extra.allow


EntryRegular.update_forward_refs()

EntryPreDbRoleModel.update_forward_refs()


EntryLangUpdate.update_forward_refs()
