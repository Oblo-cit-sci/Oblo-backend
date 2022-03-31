from logging import getLogger
from typing import Dict, List, Union, Any, Optional, Literal

from pydantic import (
    BaseModel,
    validator,
    constr,
    root_validator,
    Extra,
    ValidationError,
)
from pydantic.error_wrappers import ErrorWrapper

from app.settings import env_settings
from app.util.consts import COMPOSITE, LIST, aspect_types

logger = getLogger(__name__)


class AspectBaseIn(BaseModel):
    name: str
    type: str
    attr: Optional["AspectAttributeBase"]
    items: Optional[Union[str, "TreeItem", "ItemSourceBase", "ItemListBase"]]
    list_items: Optional["AspectBaseIn"]
    components: Optional[List["AspectBaseIn"]]
    view: Optional[dict]  # used by location aspect in local obs atm.
    comment: Optional[Any]
    options: Optional[List["AspectBaseIn"]]  # OptionsAspect
    geo_features: Optional[List["GeoFeaturesBase"]]  # be more specific

    @validator("type", pre=True)
    def validate_type(cls, value):
        if value not in aspect_types:
            raise ValueError(f"{value} is not a valid aspect type")
        return value

    @validator("list_items", pre=True)
    def validate_list_items(cls, value, values):
        if values["type"] == LIST and not value:
            logger.warning(
                f"aspect: {values['name']} of type 'list' is missing 'list_items'"
            )
            raise ValidationError([ErrorWrapper(Exception(), "")], AspectBaseIn)
        else:
            return AspectBaseIn.parse_obj(value)

    @validator("components", pre=True)
    def validate_components(cls, value, values):
        if values["type"] == COMPOSITE and not value:
            logger.warning(
                f"aspect: {values['name']} of type 'composite' is missing 'components'"
            )
            return []
        else:
            return [AspectBaseIn.parse_obj(component) for component in value]

    class Config:
        extra = env_settings().MODEL_CONFIG_EXTRA


# todo use this for values? codes but not for list-aspect items, which describes another aspect
# better name list-select-base
class ItemListBase(BaseModel):
    __root__: List["ItemBase"]

    @validator("__root__", pre=True)
    def items_val(cls, values):
        if isinstance(values, dict):
            raise ValueError("not a ItemListLang")
        return [{"value": v} if isinstance(v, str) else v for v in values]


class TreeItem(BaseModel):
    levels: ItemListBase
    root: "ItemBase"


class TreeLang(BaseModel):
    levels: "ItemListLang"
    root: "ItemLang"


class ItemBase(BaseModel):
    value: constr(max_length=64)
    icon: Optional[str]
    additional: Optional[Any]
    tag: Optional[str]
    condition: Optional[dict]
    merge: Optional[list]
    extra: Optional[dict]  # for now just "type", general_licci_tree
    children: Optional[ItemListBase]

    class Config:
        extra = env_settings().MODEL_CONFIG_EXTRA


class AspectLangIn(BaseModel):
    label: Optional[str]
    description: Optional[str] = ""
    items: Optional["ItemListLang"]
    components: Optional[List["AspectLangIn"]]
    attr: Optional["AspectAttributeLang"]
    list_items: Optional["AspectLangIn"]


class AspectLangOut(BaseModel):
    label: Optional[str]
    description: Optional[str] = ""
    items: Optional["ItemListLangOut"]
    components: Optional[List["AspectLangOut"]]
    attr: Optional["AspectAttributeLang"]
    list_items: Optional["AspectLangOut"]


class AspectAttributeLang(BaseModel):
    default_view_text: Optional[str] = None


class ItemListLang(BaseModel):
    __root__: Optional[List["ItemLang"]]

    @validator("__root__", pre=True)
    def items_val(cls, values):
        if isinstance(values, str):
            return None
        if isinstance(values, dict):
            raise ValueError("not a ItemListLang")
        if isinstance(values, list) and isinstance(values[0], str):
            return [{"text": v} for v in values]
        else:
            return [ItemLang.parse_obj(v) for v in values]


class ItemListLangOut(BaseModel):
    __root__: Optional[List["ItemLangOut"]]

    @validator("__root__", pre=True)
    def items_val(cls, values):
        if isinstance(values, str):
            return None
        else:
            return [ItemLang.parse_obj(v) for v in values]


class ItemLang(BaseModel):
    text: str
    children: Optional[List["ItemLang"]]
    description: Optional[str]
    extra: Optional[dict]  # used for the licci-tree
    rel: Optional[str]  # used for cc_licenses

    class Config:
        extra = Extra.ignore


class ItemLangOut(ItemLang):
    text: str
    description: Optional[str]

    class Config:
        extra = "ignore"


class AspectAttributeBase(BaseModel):
    # general
    page: Optional[int]

    min: Optional[Union[int, Literal["%current_year"]]]
    max: Optional[Union[int, Literal["%current_year"]]]
    suffix: Optional[str]  # for numbers
    descr_as_html: Optional[bool]
    required: Optional[bool]
    hide_on_disabled: Optional[bool]
    # select aspect
    force_view: Optional[Literal["select", "list"]]
    # ref_value
    mode: Optional[Literal["view", "edit"]]
    disable: Optional[bool]
    action: Optional[Dict]
    value: Any = None
    condition: Optional[Union[List, "AspectConditionAttribute"]]
    visible: Optional[bool]
    cache: Optional[bool]
    items_per_page: Optional[int]  # used for list-aspects, list-items
    # todo should be extensible, works only in str type? or needs some kind of value loc
    view_component: Optional[Literal["url"]]

    edit_component: Optional[str]  # used in licci base domain, for multiselect
    no_border: Optional[bool]  # used in licci base domain, for multiselect
    no_text: Optional[bool]  # used in licci base domain, for multiselect
    max_cell_width: Optional[int]  # used in licci base domain, for multiselect
    # composite:
    collapsable: Optional[bool]
    # location aspect
    input: Optional[List[str]]
    output: Optional[List[str]]
    force_public_location: Optional[Literal["exact", "random", "region"]]
    # list aspect
    add_label: Optional[str]
    # tree-select
    direct_select: Optional[bool]
    direct_select_levels: Optional[List[int]]
    allow_select_levels: Optional[List[Union[int, str]]]
    # not sure if another aspect is using this. but in tree its replaced by : tree_select_mode
    edit: Optional[List[str]]
    tree_select_mode: Optional[
        List[Literal["list", "list.list", "list.select", "large_list", "matrix", "paginated"]]
    ]
    # geometry-aspect
    use_default_style: Optional[bool]
    show_place_name: Optional[bool]
    #
    show_dialog: Optional[bool] = True
    # select in general... for now just tree?
    data_source: Optional[str]
    # new tag schema
    tag: Optional[Union[List[Dict], Dict]]  # name, subpath, comment
    # for composites
    # deprecated use:
    # - use_components_as_conditionals (as before)
    # - merge_in_components_as_conditionals
    add_components_as_conditionals: Optional[bool]  # deprecated
    use_components_as_conditionals: Optional[bool]
    merge_in_components_as_conditionals: Optional[bool]
    #
    titleAspect: Optional[bool]  # for the entry todo deprecated
    titleComponent: Optional[Union[str, List[str]]]
    service: Optional[str]  # for ExternalAccount Aspect
    verify: Optional[bool]  # for ExternalAccount Aspect

    class Config:
        # make it dependent from the environment
        extra = "forbid"


class AspectConditionAttribute(BaseModel):
    disabled_text: Optional[str]
    aspect: str
    value: Any
    compare: Optional[Literal["equal", "unequal", "contains"]]
    default_pass: Optional[bool] = None

    class Config:
        extra = "forbid"


class TextAspect(BaseModel):
    max: int


class NumberAspect(BaseModel):
    suffix: Optional[str]
    min: Optional[int]
    max: Optional[int]


class ListAspectBase(BaseModel):
    list_items: AspectBaseIn
    indexTitle: bool = False


class CompositeAspectBase(BaseModel):
    components: List[AspectBaseIn]


class ListAspectAttr(AspectAttributeBase):
    force_panels: bool = False
    moveable: bool = False


class ItemSourceBase(BaseModel):
    source: str


class GeoFeaturesBase(BaseModel):
    type: List[Literal["Point", "LineString", "Polygon"]]
    name: str
    allow_multiple: Optional[bool]
    show_place_name: Optional[bool]
    properties: Optional[List[AspectBaseIn]]
    marker_color: Optional[str]
    style: Union[Optional["GeoFeaturesStyle"], Optional[
        Dict[Literal["Point", "LineString", "Polygon"], Union[
            Literal["Point", "LineString", "Polygon"], "GeoFeaturesStyle"]]],
                 None]


class GeoFeaturesStyle(BaseModel):
    type: Literal["circle", "line", "fill"]
    paint: Optional[dict]  # mapbox point props
    layout: Optional[dict]  # mapbox layout props


# class SelectAspectBase(BaseModel):
#     items: Union[str, "AspectSourceDescription", "ItemListBase"]


# class TreeSelectAspectBase(SelectAspectBase):
#     attr: "TreeSelectAspectAtrributeBase"
#
#
# class TreeSelectAspectAtrributeBase(AspectAtrributeBase):
#     direct_select: bool = False
#     allow_select_levels: List[Union[int, str]]
#     edit: Literal["list", "large_list", "matrix"]


class LocationAspect(BaseModel):
    pass


class AspectActionBase(BaseModel):
    name: str
    type: str
    trigger: "AspectActionTriggerBase"
    properties: "AspectActionPropertiesBase"


class AspectActionTriggerBase(BaseModel):
    type: str


class AspectActionTriggerLang(AspectActionTriggerBase):
    button_label: str  # not Base but Lang


class AspectActionPropertiesBase(BaseModel):
    pass


class AspectLangSourceItem(BaseModel):
    source_text: Optional[str] = ""  # the name (label) of the source

    @root_validator(pre=True)
    def check_items(cls, values):
        if isinstance(values, dict):
            return values
        raise ValueError("items must be a dict")


class AspectLang(BaseModel):
    label: Optional[str] = ""
    description: Optional[str] = ""
    # items dict: for {source:... }will be made empty so its not put in a csc, table,
    # todo: currently {source:xxx} is added to csv downloads...
    items: Optional[Union[
        "ItemListLang", AspectLangSourceItem, "TreeLang"]]
    components: Optional[List["AspectLang"]]
    list_items: Optional["AspectLang"]
    attr: Optional["AspectAttributeLang"]
    options: Optional[List["AspectLang"]]
    geo_features: Optional[List["GeoFeaturesLang"]]

    @root_validator(pre=True)
    def check_items(cls, values):
        # this is required for db-obj to model
        # kick out when items is just a slug...
        if isinstance(values.get("items"), str):
            del values["items"]
            return values
        return values


class ItemMerge(ItemLang):
    value: str
    children: Optional[List["ItemMerge"]]
    icon: Optional[str]
    # mode: tree-select modes per level (TreeLeafpicker)
    mode: Optional[Literal[
        "matrix", "list.list", "list.select", "large_list", "paginated"]]


class ItemSourceMerge(BaseModel):
    source: str
    source_text: Optional[str] = ""


class AspectMerge(BaseModel):
    name: str
    type: str
    attr: Optional["AspectAttributeMerge"] = None
    items: Optional[
        Union[str, "TreeItemMerge", List["ItemMerge"], "ItemSourceMerge"]
    ]  # list (or tree root) # todo a tree...
    list_items: Optional["AspectMerge"]
    components: Optional[List["AspectMerge"]]
    options: Optional[List["AspectMerge"]]
    view: Optional[dict]  # used by location aspect in local obs atm.
    comment: Optional[Any]
    label: Optional[str]
    description: Optional[str] = ""
    geo_features: Optional[List["GeoFeaturesMerge"]]


class TreeItemMerge(BaseModel):
    levels: List["ItemMerge"] # TODO Something derived from ItemMerge that includes "mode"
    root: "ItemMerge"


class AspectAttributeMerge(AspectAttributeBase):
    default_view_text: Optional[str] = None


class GeoFeaturesLang(BaseModel):
    label: str
    properties: Optional[List["AspectLang"]]


class GeoFeaturesMerge(GeoFeaturesBase, GeoFeaturesLang):
    properties: Optional[List["AspectMerge"]]


class AspectLangUpdate(AspectLang):
    label: str = ""
    description: str = ""
    items: Optional["ItemListLang"]
    components: Optional[List["AspectLangUpdate"]]
    list_items: Optional["AspectLangUpdate"]
    attr: Optional["AspectAttributeLang"]

    @root_validator(pre=True)
    def check_items(cls, values):
        # this is required for db-obj to model
        # kick out when items is just a slug...
        if isinstance(values.get("items"), str):
            del values["items"]
            return values
        return values


AspectActionBase.update_forward_refs()
AspectBaseIn.update_forward_refs()
# SelectAspectBase.update_forward_refs()
AspectAttributeBase.update_forward_refs()
ItemListBase.update_forward_refs()
ItemListLang.update_forward_refs()
AspectLangOut.update_forward_refs()
ItemListLangOut.update_forward_refs()
AspectLangIn.update_forward_refs()
AspectLang.update_forward_refs()
TreeLang.update_forward_refs()
TreeItem.update_forward_refs()
AspectMerge.update_forward_refs()
ItemMerge.update_forward_refs()
ItemLang.update_forward_refs()
TreeItemMerge.update_forward_refs()
AspectAttributeMerge.update_forward_refs()
GeoFeaturesMerge.update_forward_refs()
GeoFeaturesBase.update_forward_refs()
