from typing import Optional, List, Dict, Literal, Union, Any

import orjson
from pydantic import Extra, constr, UUID4, validator, BaseModel

from app.models.orm import EntryEntryAssociation, Entry
from app.models.schema import (
    aspect_models,
    AbstractEntry,
    EntryRef,
    EntryActorRelationOut,
    FileAttachment,
    InConfig,
)
from app.models.schema.aspect_models import AspectMerge, ItemMerge, AspectLang
from app.models.schema.entry_schemas import AbstractEntryBase, EntryTagDB, CodeValuesLang
from app.settings import env_settings
from app.util.consts import PUBLIC, TYPE, BASE_CODE, SLUG, VALUE_TREE, VALUE_LIST
from app.util.files import orjson_dumps


def convert_db_entry_refs(v: Union["EntryEntryRef", dict, EntryEntryAssociation]):
    if isinstance(v, EntryEntryRef):
        return v
    elif isinstance(v, dict):
        return EntryEntryRef.parse_obj(v)
    elif isinstance(v, EntryEntryAssociation):
        return EntryEntryRef.parse_obj({**v.reference, "dest_slug": v.destination.slug})


class AbstractEntryCodeTemplate(AbstractEntry):
    slug: constr(max_length=255)
    uuid: Optional[UUID4]
    template: Optional[EntryRef]
    privacy: Literal["public", "private"] = PUBLIC
    license: str = "CC0"
    config: Optional[dict] = {}
    entry_refs: List["EntryEntryRef"] = []
    rules: "TemplateBaseRules" = {}
    actors: List[EntryActorRelationOut] = []
    version: Optional[int]

    validate_entry_refs = validator(
        "entry_refs", pre=True, each_item=True, allow_reuse=True
    )(convert_db_entry_refs)

    class Config:
        orm_mode = True


# this is used for basic and language based entries to be mixed
class TemplateBaseInit(AbstractEntryCodeTemplate):
    # todo: later remove schema for another type
    type: Literal["schema", "base_template", "base_code"]  # maybe take from consts
    template: Optional[EntryRef]
    aspects: Optional[List[aspect_models.AspectBaseIn]] = []
    values: Optional[Dict] = {}  # todo: maybe a EntryBaseValues

    @validator("template", pre=True, always=True)
    def template_verifier(cls, value, values):
        # print(f"template validator: {value}, {values[TYPE]}, {values}")
        if values[TYPE] == BASE_CODE:
            if isinstance(value, Entry):
                template_slug = value.slug
            else:
                template_slug = value[SLUG]
            if (not value) or (template_slug not in [VALUE_TREE, VALUE_LIST]):
                raise ValueError(
                    f"codes must have a schema-template of {[VALUE_TREE, VALUE_LIST]}, given: {template_slug}")
        return value

    class Config:
        orm_mode = True
        json_loads = orjson.loads
        json_dumps = orjson_dumps


class TemplateBaseRules(BaseModel):
    """
    rules are only for Base entries
    todo can be private if EntryIn is not used for regular entries anymore
    """

    context: Optional[str]  # only relevant for templates
    one_aspect_per_page: Optional[bool]
    edit_mode_question_only: Optional[bool]
    view_mode_hide_unset_values: Optional[bool]
    # allow_base_only: Optional[bool]  # try insert even if no lang entry is given , try to parse as lang too?
    base_lang: Optional[str]  # this or default lang
    titleAspect: Optional[
        str
    ]  # aspect loc of aspect that makes up the title of the entry
    search_in: Optional[
        List[str]
    ]  # not yet implemented in this version, cuz backend. should search in values...
    tagsAspects: Optional[Dict[str, str]]  # name:location for tags
    marker_color: Optional[str]
    preview: Optional[dict]  # exists somewhere but not sure if used in any way
    tags: Optional[Dict] = {}  # fore code entries
    # persistent base-code (value_list, value_tree), also lang-entries will have this (their template is code_base)
    code_schema: Optional[str]
    locationAspect: Optional[str]  # the aspect from which the entry-location metadata is taken
    requires_review_if_missing: Optional[
        List[str]]  # entry is set to requires_review if any of these aspects is missing
    allow_download: Optional[bool]
    data_source: Optional[str]  # for code entries. take the icons from this data source (entry-slug)
    allow_duplicates_on_levels: Optional[list] = []  # used for value_tree code-entries
    pages: Optional[List["TemplateBasePages"]] = None
    geometry_aspect: Optional[str]  # for automatic map.fitBounds when entry is selected

    class Config:
        extra = Extra.forbid


class TemplateBasePages(BaseModel):
    condition: Optional["TemplateBasePagesCondition"]

    class Config:
        extra = Extra.forbid


class TemplateBasePagesCondition(BaseModel):
    aspect: str
    value: Any
    compare: Optional[Literal["equal", "unequal", "contains"]]

    class Config:
        extra = Extra.forbid


class TemplateLang(AbstractEntryBase):
    title: str
    description: str = ""
    aspects: List[AspectLang] = []
    values: Optional["CodeValuesLang"]
    # exclude for csv!!! entry_ctrl.entry_as_csv
    language: str
    type: str  # can be more concrete
    template: Optional[EntryRef]
    # todo not sure
    config: dict
    domain: str
    slug: str
    rules: Optional["TemplateLandRules"]  # pages, todo move it, so rules stays lang-free

    class Config:
        orm_mode = True
        extra = Extra.forbid if env_settings().ENV == "dev" else Extra.ignore


class TemplateLandRules(BaseModel):
    pages: Optional[List["TemplateLangRulesPages"]] = None


class TemplateLangRulesPages(BaseModel):
    title: Optional[str]
    description: Optional[str]


class TemplateMerge(AbstractEntryCodeTemplate):
    title: str
    type: Literal["template", "code"]  # maybe take from consts
    description: Optional[str] = ""
    aspects: List["AspectMerge"] = []
    values: Optional["ValuesMerge"]
    rules: Optional["TemplateMergeRules"] = {}

    class Config:
        orm_mode = True
        extra = Extra.forbid if env_settings().ENV in ["test", "dev"] else Extra.ignore


class TemplateMergeRules(TemplateBaseRules):
    pages: Optional[List["TemplateMergeRulesPages"]] = None


class TemplateMergeRulesPages(TemplateBasePages, TemplateLangRulesPages):
    pass


class EntryEntryRef(BaseModel):
    dest_slug: str
    ref_type: Literal["code", "tag"]
    aspect_path: str
    tag: Optional[Union[List[Dict], dict]]


class ValuesMerge(BaseModel):
    root: Optional["ItemMerge"]
    levels: Optional[List["ItemMerge"]]
    list: Optional[List["ItemMerge"]]

    long_description: Optional[str]  # for some templates


class EntryMergeRules(TemplateBaseRules, TemplateLandRules):
    pages: Optional[List["TemplateMergePages"]]


class TemplateMergePages(TemplateBasePages, TemplateLangRulesPages):
    pass


class CodeTemplateMinimalOut(AbstractEntryBase):
    """
    used for the TranslationSetupComponent
    todo. version?
    """

    # todo test, if template can be left away but validator is still used...
    template: Optional[EntryRef]
    status: str

    class Config:
        orm_mode = True
        arbitrary_types_allowed = True

    @validator("template", pre=True)
    def convert_entry_refs(cls, v):
        if not v:
            return ""
        else:
            return v.slug


# TODO: fix usage. in update_entry (template/code) and init.insert_regular_entry
# todo then move to template_code_entry_schema.py
class EntryIn(AbstractEntryBase):
    # todo: can go? inherit...
    description: Optional[str] = ""
    location: Optional[List[Dict]]
    # Optional[Union[List[LocationBase], Dict[str, Union[LocationBase, List[LocationBase]]]]]
    actors: List[EntryActorRelationOut] = []
    # beware of the change. we take the
    tags: List["EntryTagDB"] = []  # FROM Dict[str, List[str]] = {}

    aspects: List["AspectMerge"] = []
    entry_refs: List["EntryEntryRef"] = []
    values: Dict = {}
    rules: Optional["TemplateBaseRules"] = {}
    attached_files: List[
        FileAttachment
    ] = []  # or actually a document model, which has, entry similar fields
    config: Optional[dict] = {}

    @validator("tags", pre=True, always=True)
    def tags_validator(cls, value):
        if isinstance(value, dict):
            result: List[EntryTagDB] = []
            for group_name, tag in value.items():
                result.append(EntryTagDB(tag=tag, group_name=group_name))
            return result
        else:
            return value

    class Config(InConfig):
        orm_mode = True


ValuesMerge.update_forward_refs()
TemplateBaseInit.update_forward_refs()
TemplateBaseRules.update_forward_refs()
TemplateBasePages.update_forward_refs()
TemplateLandRules.update_forward_refs()
TemplateLang.update_forward_refs()
TemplateMerge.update_forward_refs()
TemplateMergeRules.update_forward_refs()
TemplateMergeRulesPages.update_forward_refs()
EntryIn.update_forward_refs()
