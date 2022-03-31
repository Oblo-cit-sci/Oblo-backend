from csv import DictReader
from logging import getLogger
from typing import List, Dict, Iterable, Tuple, Sequence

from app.models.schema import TemplateMerge
from app.models.schema.aspect_models import AspectMerge
from app.util.consts import TERMINAL_ASPECT_TYPES, LIST, COMPOSITE, OPTIONS
from app.util.data_import.models import Mapping, MappingAspectOutput, MappingValueInput, AspectMappingDefinition, \
    AspectMappingDefinitionExceptionalValue
from app.util.files import CSVPath

logger = getLogger(__name__)


def validate_mapping(template_model: TemplateMerge, zipped_tables_and_readers: Iterable[Tuple[CSVPath, DictReader]],
                     value_mapping: Mapping, ignore_columns: Sequence[str] = ()) -> Tuple[
    Dict[MappingValueInput, MappingAspectOutput], str]:
    """
    @param template_model: the template model
    @param zipped_tables_and_readers: files and readers
    @param value_mapping: the user given mapping from columns to aspectpaths
    @ignore_columns: columns that should be ignored
    @return: a mapping from input fields to aspect outputs and the id field
    """

    # first run-over to get all fieldnames
    document_fieldnames = {
        path.name: [header.strip() for header in reader.fieldnames if header not in ignore_columns]
        for path, reader in zipped_tables_and_readers
    }

    id_field: str = list(document_fieldnames.values())[0][0]
    all_input_fields: List[MappingValueInput] = validate_input_sources(document_fieldnames)
    assigned_input_fields: Dict[
        MappingValueInput, AspectMappingDefinition] = validate_input(all_input_fields, value_mapping)

    all_mapping_outputs: List[MappingAspectOutput] = generate_acceptable_paths(template_model)

    error_paths, missing_paths, final_mapping = validate_output(assigned_input_fields, all_mapping_outputs)

    # error_paths, missing_paths, column_aspect_pos_mapping = \
    #     validate_mapping_aspect_locations(value_mapping, all_mapping_outputs, document_fieldnames)

    if len(error_paths) > 0:
        logger.warning("")
        logger.warning(f"Error paths:\n")
        for error in error_paths:
            logger.warning(f"{error}")
    if len(missing_paths) > 0:
        logger.warning("")
        logger.warning(f"Missing paths:\n")
        for missing in missing_paths:
            logger.warning(f"{missing}")
    return final_mapping, id_field


def validate_input_sources(document_fieldnames: dict[str, List[str]]) -> List[MappingValueInput]:
    # validate first columns
    id_header_candidate: str = list(document_fieldnames.values())[0][0]
    # result items:
    result_items: List[MappingValueInput] = []
    # check if first fields of all sources are the same
    for doc_name, fieldnames in document_fieldnames.items():
        if (first := fieldnames[0]) != id_header_candidate:
            raise ValueError(
                f"All tables must have the same id header. Document: {doc_name} has first header: "
                f"{first} instead of {id_header_candidate}")
        # this is not the most optimal, but it allows us to to print the sources right away, and allows us
        # later to configure that we dont care about duplicates but ignore them
        for field in fieldnames[1:]:
            input_item = MappingValueInput(field=field, source=doc_name)
            for item in result_items:
                if item.field == field:
                    raise ValueError(
                        f"Duplicate field: {field} in document: {doc_name} already exists in {item.source}")
            result_items.append(input_item)

    return result_items


def validate_input(all_input_fields: List[MappingValueInput], value_mapping: Mapping) -> Dict[
    MappingValueInput, AspectMappingDefinition]:
    """
    throw error for mapping-inputs that don't exist
    and return table header that are missing in the mapping
    """
    # input_fields = [item.field for item in all_input_fields]
    # find mapping keys that are not in input fields
    mapping_inputs = list(value_mapping.keys())
    for mapping_column in mapping_inputs:
        if mapping_column not in all_input_fields:
            raise ValueError(f"validate_mapping_columns: '{mapping_column}' defined in mapping is not in table header")

    # check which input fields are used and which not
    unassigned_input_fields: List[MappingValueInput] = all_input_fields[:]
    assigned_input_fields = {}
    for input_field in all_input_fields:
        if input_field.field in mapping_inputs:
            unassigned_input_fields.remove(input_field)
            assigned_input_fields[input_field] = value_mapping[input_field.field]
    if unassigned_input_fields:
        unassigned_str = '\n'.join((repr(f) for f in unassigned_input_fields))
        logger.warning(f"Unassigned inputs:\n{unassigned_str}")
        logger.warning("")
    return assigned_input_fields


def validate_output(mapping: Dict[MappingValueInput, AspectMappingDefinition],
                    template_aspects_paths: List[MappingAspectOutput]) -> Dict[MappingValueInput, MappingAspectOutput]:
    errors = []
    # needs to be string in order to add both the regular aspect_pos but also the exceptional_aspect_pos
    found_aspect_positions: List[str] = []

    final_mapping_pairs: Dict[MappingValueInput, MappingAspectOutput] = {}
    # column_aspect_pos_mapping: dict[str, MappingAspectOutput] = {}

    for input, mapping_aspect_definition in mapping.items():
        aspect_pos = mapping_aspect_definition.aspect_pos

        if aspect_pos not in template_aspects_paths:
            errors.append((input, aspect_pos))
            continue

        # aspect_pos are not allowed to appear twice
        if aspect_pos in found_aspect_positions:
            raise ValueError(f"path {aspect_pos} appears twice in mapping")

        found_aspect_positions.append(mapping_aspect_definition.get_path())
        aspect_output = template_aspects_paths[template_aspects_paths.index(mapping_aspect_definition)]
        aspect_output.assigned_input = input
        aspect_output.mapping_definition = mapping_aspect_definition
        final_mapping_pairs[input] = aspect_output

        if isinstance(mapping_aspect_definition, AspectMappingDefinitionExceptionalValue):
            # noinspection PyUnresolvedReferences
            exceptional_value_aspect_pos = mapping_aspect_definition.exceptional_aspect_pos
            if exceptional_value_aspect_pos not in template_aspects_paths:
                errors.append((input, exceptional_value_aspect_pos))
            elif exceptional_value_aspect_pos in found_aspect_positions:
                raise ValueError(f"exceptional path of {aspect_pos}: {exceptional_value_aspect_pos}"
                                 f"appears twice in mapping ??")
            else:
                found_aspect_positions.append(exceptional_value_aspect_pos)
                mapping_aspect_definition.types = template_aspects_paths[
                    template_aspects_paths.index(mapping_aspect_definition.exceptional_aspect_pos)].types

    missing_paths = [aspect_position for aspect_position in template_aspects_paths
                     if aspect_position not in found_aspect_positions]
    return errors, missing_paths, final_mapping_pairs


def generate_acceptable_paths(template: TemplateMerge) -> List[MappingAspectOutput]:
    """
    replace tuple by a named tuple... str for the path and int for the required integer for list indices
    """

    def generate_path_for_aspect(aspect: AspectMerge, parents: List[AspectMerge] = []) -> List[MappingAspectOutput]:
        if aspect.type in TERMINAL_ASPECT_TYPES:
            num_lists = 0
            node_names = []
            types = []
            for node in parents:
                if node.type == LIST:
                    num_lists += 1
                node_names.append(node.name)
                types.append(node.type)
            node_names.append(aspect.name)
            types.append(aspect.type)
            path = ".".join(node_names)
            return [MappingAspectOutput(path, types, aspect)]
        else:
            if aspect.type == LIST:
                return generate_path_for_aspect(aspect.list_items, parents + [aspect])
            elif aspect.type == COMPOSITE:
                component_paths = []
                for component in aspect.components:
                    component_paths.extend(generate_path_for_aspect(component, parents + [aspect]))
                return component_paths
            elif aspect.type == OPTIONS:
                logger.warning("OPTIONS not yet supported")
                pass

    paths = []
    for aspect in template.aspects:
        paths.extend(generate_path_for_aspect(aspect))
    return paths
