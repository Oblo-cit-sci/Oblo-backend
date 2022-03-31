from typing import Dict, List, Optional

from pydantic import validator, conlist
from pydantic.main import BaseModel

from app.models.schema import aspect_models
from app.models.schema.aspect_models import ItemListLang
from app.settings import env_settings


# if TYPE_CHECKING:
#     from app.models.orm.domain_meta import DomainMeta


def default_language_validator(value):
    return value if value else env_settings().DEFAULT_LANGUAGE


class DomainBase(BaseModel):
    name: str
    index: int
    content: "DomainBaseContent"
    is_active: bool = True
    default_language: str = None

    default_language_validator = validator(
        "default_language", pre=True, always=True, allow_reuse=True
    )(default_language_validator)

    class Config:
        orm_mode = True


class DomainBaseContent(BaseModel):
    users: Optional["_DomainBaseUsers"] = {}
    search: Optional["_DomainBaseSearch"] = {}
    filters: Optional["_DomainBaseFilters"] = {}
    map: Optional["_DomainBaseMap"] = {}
    required_entries: Optional[List[str]] = []
    entry: Optional[dict] = {}
    include_entries: Optional[list] = []
    footer_logos: Optional[List["_FooterBaseLogos"]] = []


class _FooterBaseLogos(BaseModel):
    logo: str
    link: str


class _DomainBaseUsers(BaseModel):
    profile: Optional["_DomainBaseUsersProfile"]


class _DomainBaseUsersProfile(BaseModel):
    additional_aspects: Optional[List[aspect_models.AspectBaseIn]]


class _DomainBaseSearch(BaseModel):
    default_templates: Optional[conlist(str, min_items=1)]


class _DomainBaseFilters(BaseModel):
    prominent_filters: Optional[List["_FilterBase"]]


class _FilterBase(BaseModel):
    name: str
    aspect: aspect_models.AspectBaseIn
    search_config: Dict  # more later


class _DomainBaseMap(BaseModel):
    layers: Optional["aspect_models.ItemListBase"] = []
    default_active_layers: Optional[List[str]] = []
    init_map_options: Optional[Dict] = None
    additional_layers = []


class _DomainBaseRef(BaseModel):
    name: str
    index: int
    is_active: bool = True
    default_language: str = None

    default_language_validator = validator(
        "default_language", pre=True, always=True, allow_reuse=True
    )(default_language_validator)

    class Config:
        orm_mode = True


class DomainLang(BaseModel):
    title: str
    language: str
    content: "DomainLangContent"
    domainmeta: Optional[_DomainBaseRef] = None
    is_active: bool = False

    class Config:
        orm_mode = True


class DomainLangContent(BaseModel):
    long_title: Optional[str] = None
    description: Optional[str] = ""
    short_description: Optional[str] = None
    users: Optional["_DomainLangUsers"] = {}
    # search: Optional["_DomainLangSearch"] = {}
    filters: Optional["_DomainLangFilters"] = {}
    map: Optional["_DomainLangMap"] = {}
    about: Optional[list]
    guidelines: Optional[dict] = {}

    class Config:
        orm_mode = True


class _DomainLangUsers(BaseModel):
    profile: Optional["_DomainLangUsersProfile"]


class _DomainLangUsersProfile(BaseModel):
    additional_aspects: Optional[List["aspect_models.AspectLangIn"]]


class _DomainLangSearch(BaseModel):
    default_templates: Optional[List[str]]



class _DomainLangFilters(BaseModel):
    prominent_filters: Optional[List["_FilterLang"]]


class _DomainLangMap(BaseModel):
    layers: Optional["ItemListLang"]


class _FilterLang(BaseModel):
    aspect: aspect_models.AspectLangIn

    class Config:
        orm_mode = True


class DomainOut(BaseModel):
    name: str
    index: int
    languages: List[str] = []
    default_language: str
    langs: Dict[str, Dict] = {}  # actually domain-lang
    overviews: Dict[str, "DomainMinimumLangOut"] = {}
    include_entries: Optional[List[str]] = []

    class Config:
        orm_mode = True


class DomainMinimumLangOut(BaseModel):
    title: str
    description: str


class DomainMetaInfoOut(BaseModel):
    """
    this is used for translation
    """

    name: str
    index: int
    default_language: str
    is_active: bool
    active_languages: List[str] = []
    inactive_languages: List[str] = []
    required_entries: List[str] = []
    all_codes_templates: List[str] = []

    class Config:
        orm_mode = True


DomainOut.update_forward_refs()
DomainBase.update_forward_refs()
DomainOut.update_forward_refs()
_DomainLangMap.update_forward_refs()
_DomainLangFilters.update_forward_refs()
_DomainLangUsersProfile.update_forward_refs()
_DomainLangUsers.update_forward_refs()
DomainLangContent.update_forward_refs()
DomainBaseContent.update_forward_refs()
DomainLang.update_forward_refs()
_DomainBaseMap.update_forward_refs()
_DomainBaseUsers.update_forward_refs()
_DomainBaseFilters.update_forward_refs()
