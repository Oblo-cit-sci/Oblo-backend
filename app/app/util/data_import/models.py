from dataclasses import dataclass
from typing import List, Optional, Union, Dict, Tuple, Literal, get_args, Any

from pydantic import BaseModel, root_validator, ValidationError

from app.models.schema import TemplateMerge
from app.models.schema.aspect_models import AspectMerge


class MappingValueInput(BaseModel):
    """
    model for input definition in a mapping (field name and source)
    """
    field: str
    source: str

    def __eq__(self, other: Union[str, "MappingValueInput"]) -> bool:
        if isinstance(other, str):
            return self.field == other
        return self.field == other.field and self.source == other.source

    def __repr__(self) -> str:
        return f"ValueInput:({self.field!r}, {self.source!r})"

    def __hash__(self):
        return hash(self.field)


class AspectMappingDefinitionBase(BaseModel):
    """
    base class for a destination in the  mapping definition (what a field maps to)
    """
    aspect_pos: str

    def get_path(self) -> str:
        return self.aspect_pos

    def __eq__(self, other: Union[str, "AspectMappingDefinitionBase"]) -> bool:
        if isinstance(other, str):
            return self.aspect_pos == other
        return self.aspect_pos == other.aspect_pos


class AspectMappingDefinitionExceptionalValue(AspectMappingDefinitionBase):
    exceptional_aspect_pos: str
    activator_value: str  # value that should be assigned on the original aspect_pos
    #
    types: Optional[List[str]] # set later in validation


class AspectMappingDefinitionJSON(AspectMappingDefinitionBase):
    parse_json: bool


AspectMappingDefinition = Union[
    AspectMappingDefinitionExceptionalValue, AspectMappingDefinitionJSON, AspectMappingDefinitionBase]

# AlternativeMappingDefinitions =[AspectMappingDefinitionExceptionalValue,AspectMappingDefinitionJSON]

@dataclass
class MappingAspectOutput:
    """
    model for description of a aspect in a template. mapping_definition is added during validation
    """
    aspect_pos: str
    # list_indices_len: int
    types: List[str]
    aspect: AspectMerge
    code_entry: Optional[TemplateMerge] = None
    # added during validation
    assigned_input: Optional[MappingValueInput] = None
    mapping_definition: Optional[AspectMappingDefinition] = None

    def __hash__(self):
        return hash(self.aspect_pos)

    def __eq__(self, other: Union[str, "MappingAspectOutput", "AspectMappingDefinition"]) -> bool:
        if isinstance(other, str):
            return self.aspect_pos == other
        if isinstance(other, get_args(AspectMappingDefinition)):
            return self.aspect_pos == other.get_path()
        return self.aspect_pos == other.aspect_pos

    def __repr__(self):
        return f"MappingAspectOutput:({self.aspect_pos!r}, {self.aspect.type!r})"


class Mapping(BaseModel):
    __root__: Dict[str, AspectMappingDefinition]

    @root_validator(pre=True)
    def check_items(cls, values):
        for mapping_source, mapping_destination in values["__root__"].items():
            if isinstance(mapping_destination, str):
                values["__root__"][mapping_source] = AspectMappingDefinitionBase(aspect_pos=mapping_destination)
            # else:
                #
                # try:
                #     values["__root__"][mapping_source] = AspectMappingDefinitionExceptionalValue(mapping_destination)
                # except ValidationError as e:
                #     pass
        return values

    def keys(self) -> List[str]:
        for key in self.__root__.keys():
            yield key

    def values(self) -> List[AspectMappingDefinition]:
        for value in self.__root__.values():
            yield value

    def items(self) -> List[Tuple[str, AspectMappingDefinition]]:
        for key, value in self.__root__.items():
            yield key, value

    def __getitem__(self, key) -> AspectMappingDefinition:
        return self.__root__[key]


@dataclass
class ItemError:
    output_aspect: MappingAspectOutput
    value: str
    row_id: Optional[int] = None

    def __repr__(self):
        return f"({self.value!r}, {self.row_id!r})"

    def __hash__(self):
        return hash(self.value) + hash(self.row_id)


@dataclass(frozen=True)
class RowError:
    document_name: str
    row_id: int
    document_row: int
    errors: List[ItemError]

    def __post_init__(self):
        for item_error in self.errors:
            item_error.row_id = self.row_id


SelectValue = dict[str, str]
TreeValue = list[SelectValue]
MultiSelectValue = list[SelectValue]
SelectValues = Union[SelectValue, TreeValue, MultiSelectValue]

ExceptionalValue = Tuple[MappingAspectOutput, Any]
PackedSelectValue = Dict[Literal["value"], Union[SelectValues, TreeValue, MultiSelectValue]]
