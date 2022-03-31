import sys
from logging import getLogger
from typing import List, Tuple, Optional, Any, Dict, Set, Iterable, Union, Callable, Sequence
from urllib.parse import urljoin

from colorama import Fore

from app.models.orm import Entry, EntryEntryAssociation
from app.models.schema import EntryRef, TemplateMerge
from app.models.schema.entry_schemas import EntryRegular, EntryOut
from app.models.schema.template_code_entry_schema import EntryEntryRef
from app.services.util.aspect import aspect_default, pack_raw_value
from app.services.service_worker import ServiceWorker
from app.util.consts import REGISTERED_NAME, CREATOR, ACTOR, LIST, VALUE, \
    SELECT, TREE, MULTISELECT, TREEMULTISELECT, SELECT_TYPES, TEXT, TEMPLATE, VALUE_TREE, SLUG, STATUS, TAGS, \
    TEMPLATE_VERSION
from app.util.data_import.models import MappingAspectOutput, ItemError, RowError, Mapping, SelectValues, \
    ExceptionalValue, MappingValueInput, AspectMappingDefinitionExceptionalValue
from app.util.data_import.validate import validate_mapping
from app.util.files import CSVPath
from app.util.tree_funcs import find_by

logger = getLogger(__name__)


def create_regular(template: TemplateMerge, sw: ServiceWorker, username: str) -> EntryRegular:
    return sw.entry.create_empty_regular(
        template=EntryRef(
            slug=template.slug,
            language=template.language,
            version=template.version
        ),
        language=template.language,
        actors=[{
            "role": CREATOR,
            ACTOR: {
                REGISTERED_NAME: username
            }
        }]
    )


def get_prepare_templates_and_references(client, api_base_url: str, slug: str, language: str):
    url = urljoin(api_base_url,f"slug/{slug}/with_references")
    entries_respones = client.get(url, params={
        "language":language,
    })

    def to_template_merge(entry_data: dict):
        conv_data = EntryOut.parse_obj(entry_data).dict(exclude_none=True)
        for field in ["creation_ts", "last_edit_ts", STATUS, TAGS, TEMPLATE_VERSION, "attached_files"]:
            if field in conv_data:
                del conv_data[field]
        return TemplateMerge(**conv_data)

    if entries_respones.status_code == 200:
        return {
            entry_data[SLUG]: to_template_merge(entry_data) for entry_data in entries_respones.json()
        }
    else:
        print(f"Failed to get template merge for {slug}/{language} from {entries_respones.url}")
        sys.exit(1)

def import_tables(table_paths: List[CSVPath], template_model: TemplateMerge, value_mapping: Mapping,
                  sw: ServiceWorker, username: str, ignore_columns: Sequence[str] = (),
                  ref_entries: Dict[str, TemplateMerge] = {},
                  post_creation_script: Optional[Callable[[Dict[int, EntryRegular]], None]] = None) -> List[
    EntryRegular]:
    """
    take some tables and create regular entries from them. The mapping provides
    a mapping from a column to a value location (jsonpath)
    List of simple values can be comma separated, of composites must be split into multiple columns
    The first column of all tables must be an id, which can be used for composite-lists
    ! when a non composite list value appears twice an error occurs
    """
    if template_model.type != TEMPLATE:
        raise ValueError("Only entries of type templates can be used for imports")

    # template_model = TemplateMerge.from_orm(template)
    readers = [table_path.read(as_dict=True) for table_path in table_paths]

    # validation
    try:
        mapping: Dict[MappingValueInput, MappingAspectOutput]
        id_field: str
        mapping, id_field = validate_mapping(template_model,
                                             zip(table_paths, readers),
                                             value_mapping, ignore_columns)

    except ValueError as err:
        print(err)
        raise

    load_and_assign_code_entries(template_model, list(mapping.values()), ref_entries)
    id_entry_map: dict[int, EntryRegular] = {}
    all_errors = []
    for table_path, reader in zip(table_paths, readers):
        for row_index, row in enumerate(reader):
            # print(row)
            try:
                row_id = int(row[id_field])
                # print(id)
            except ValueError:
                logger.warning("id not of type integer")
            else:
                if row_id in id_entry_map:
                    entry = id_entry_map[row_id]
                else:
                    entry = create_regular(template_model, sw, username)
                    id_entry_map[row_id] = entry
                errors = read_row(row, entry, mapping)
                all_errors.append(
                    RowError(document_name=table_path.name, row_id=row_id, document_row=row_index, errors=errors))
            # maybe do it later, after all values are good
    # print([entry.values for entry in id_entry_map.values()])
    # todo bring this back
    display_errors(all_errors)
    if post_creation_script:
        post_creation_script(id_entry_map)
    return list(id_entry_map.values())


def display_errors(row_errors: List[RowError]):
    item_errors: List[ItemError] = []
    for error in row_errors:
        item_errors.extend(error.errors)

    aspect_errors_map: dict[MappingAspectOutput, Set[ItemError]] = {}
    for error in item_errors:
        aspect_errors_map.setdefault(error.output_aspect, set()).add(error)

    for aspect_out, item_errors in aspect_errors_map.items():
        # column_aspect_def = next(filter(lambda col__aspect_pos: col__aspect_pos[1].aspect_pos == aspect_pos,
        #                                 column_aspect_pos_mapping.items()))
        input_field = aspect_out.assigned_input.field
        print(Fore.GREEN + f"{aspect_out.aspect_pos} / input_field: {input_field}")
        grouped_item_errors = {}
        for item_error in item_errors:
            grouped_item_errors.setdefault(item_error.value, []).append(item_error.row_id)
        print(Fore.RED + f"Found: {list(grouped_item_errors.items())}")
        # aspect_pos: MappingAspectOutput = column_aspect_def[1]
        if not isinstance(aspect_out.aspect.items, str):
            items = aspect_out.aspect.dict(exclude_none=True)['items']
            for item in items:
                print(Fore.YELLOW + f"{item['text']} | {item['value']}")

    total_errors = 0
    for error_aspect in aspect_errors_map.values():
        total_errors += len(error_aspect)
    print(Fore.GREEN + f'{len(list(aspect_errors_map.keys()))} aspects with errors found')
    print(Fore.GREEN + f'{total_errors} errors in total found')
    print(Fore.BLACK)


def load_and_assign_code_entries(template_model: TemplateMerge, aspects: List[MappingAspectOutput],
                                 ref_entries_map: dict[str, TemplateMerge]):
    """
    loads, verifies (checks all aspects vs  slug) and assigns them to the AspectPosDefinition code_entry
    """
    references: List[EntryEntryRef] = template_model.entry_refs
    # [1:] because the first character is a dot.
    reference_aspect_path_entry_map = {ref.aspect_path[1:]: ref for ref in references}
    # ref_entries_map: Dict[int, TemplateMerge] = {}
    # map by id, so we dont generate it multiple times.
    # ref_entries_map = {ref.destination_id: TemplateMerge.from_orm(ref.destination) for ref in references if
    #                    ref.destination_id not in ref_entries_map}
    for aspect_def in aspects:
        if aspect_def.aspect.type in [SELECT, MULTISELECT, TREE, TREEMULTISELECT]:
            if isinstance(aspect_def.aspect.items, str):
                code_slug = aspect_def.aspect.items
                if aspect_def.aspect_pos not in reference_aspect_path_entry_map:
                    raise ValueError(f"No reference found for aspect {aspect_def.aspect_pos} with the slug {code_slug}")
                reference = reference_aspect_path_entry_map[aspect_def.aspect_pos]
                # this is very unlikely
                if code_slug != reference.dest_slug:
                    raise ValueError(f"reference slugs do not match: aspect at: {aspect_def.aspect_pos}. "
                                     f"slug in aspect: '{code_slug}', in reference: "
                                     f"'{reference.dest_slug}'")
                aspect_def.code_entry = ref_entries_map[code_slug]
                # print(f"assigned code entry {aspect_def.code_entry} to aspect {aspect_def.aspect_pos}")


def read_row(row: dict, entry: EntryRegular, mapping: Dict[MappingValueInput, MappingAspectOutput]) -> List[ItemError]:
    errors = []
    for key, value in row.items():
        clean_key = key.strip()
        if value:
            if clean_key in mapping:
                output_aspect: MappingAspectOutput = mapping[clean_key]
                errors.extend(set_value(entry, output_aspect, value.strip()))
    return errors


def set_value(entry: EntryRegular, output_aspect: MappingAspectOutput, value: str, list_indices: List[int] = [],
              use_exceptional_aspect_pos: bool = False) -> \
        List[ItemError]:
    def split_path(path_: str) -> List[str]:
        return path_.split(".")

    try:
        if use_exceptional_aspect_pos:
            output_aspect: AspectMappingDefinitionExceptionalValue = output_aspect
            path = output_aspect.exceptional_aspect_pos
        else:
            path = output_aspect.aspect_pos
        path_parts = split_path(path)
        current_val = entry.values
        in_list = False
        current_aspect_type = None
        current_list_index = -1  # this is not the index in the list, but which list... (tho usually just 1)
        errors: List[ItemError] = []
        for index, part in enumerate(path_parts):
            try:
                current_aspect_type = output_aspect.types[index]
                if not in_list:
                    if index > 0:  # composite
                        current_val = current_val[VALUE]
                    # top level aspect or component
                    current_val = current_val.setdefault(part, current_aspect_type)
                else:
                    if index == len(path_parts) - 1:
                        break
                    else:
                        current_val = current_val[list_indices[current_list_index]]
                if current_aspect_type == LIST:
                    in_list = True
                    current_list_index += 1
            except Exception as err:
                print(f"crash on value: {value}. {index}, {part}")
                print(err)
        # set value
        if in_list:
            list_values = [v.strip() for v in value.split(",")]
            if current_aspect_type in SELECT_TYPES:
                if current_aspect_type == MULTISELECT:
                    raise ValueError(f"MULTISELECT in list is not supported: {path}")
                result, exceptional_values, sel_errors = get_select_values(value, output_aspect, path, False)
                if result:
                    result = [pack_raw_value(item) for item in result]
                # TODO exceptional value handling
                errors.extend(sel_errors)
            else:
                result = [{VALUE: value} for value in list_values]
            current_val[VALUE] = result
        else:
            if current_aspect_type == MULTISELECT:
                select_values, exceptional_values, sel_errors = get_select_values(value, output_aspect, path)
                errors.extend(sel_errors)
                current_val[VALUE] = select_values
                if exceptional_values:
                    for (aspect_pos_def, value) in exceptional_values:
                        set_value(entry, aspect_pos_def, value, use_exceptional_aspect_pos=True)

            elif current_aspect_type in SELECT_TYPES:  # still includes MULTISELECT, but is catched before
                select_value, exceptional_value, item_error = get_select_value(value, output_aspect, path,
                                                                               False)
                if select_value:
                    current_val[VALUE] = select_value[VALUE]
                    current_val[TEXT] = select_value[TEXT]
                if item_error:
                    errors.append(item_error)
            else:
                current_val[VALUE] = value.strip()
        return errors
    except Exception as e:
        print(f"crash on {path} with {value}")
        print(e)
        # print(entry.values)


def get_select_values(value: str, output_aspect: MappingAspectOutput, path: str, use_default: bool = True) -> \
        Tuple[List[SelectValues], List[ExceptionalValue], List[ItemError]]:
    """
    this is called when we have select items in a list or a multiselect aspect
    :param value: value to split
    :param output_aspect:
    :param path: for the error
    :param use_default: if we should use the default value if the value is empty
    """
    list_values = [v.strip() for v in value.split(",")]
    result_values = []
    exceptional_values = []
    errors: List[ItemError] = []
    for value in list_values:
        select_value, exceptional_value, item_error = get_select_value(value, output_aspect, path, use_default)
        if item_error:
            errors.append(item_error)
        if exceptional_value:
            exceptional_values.append(exceptional_value)
        elif use_default or select_value:
            result_values.append(select_value)

    return result_values, exceptional_values, errors


def get_select_value(value: Any, output_aspect: MappingAspectOutput, path: str, use_default: bool = True) -> \
        Tuple[Optional[SelectValues], Optional[ExceptionalValue], Optional[ItemError]]:
    # print(value, aspect.items)
    aspect = output_aspect.aspect
    if isinstance(aspect.items, str):
        if output_aspect.code_entry.rules.code_schema == VALUE_TREE:
            entry = output_aspect.code_entry
            tree_root = entry.values.root.dict(exclude_none=True)
            tree_values, last_node_has_children = find_by(tree_root, value)
            # validation = validate_value(entry.values.dict(exclude_none=True), tree_values, aspect)
            if tree_values:
                return tree_values, None, None
            else:
                return (aspect_default(output_aspect.aspect) if use_default else None,
                        None,  # todo exceptional value?
                        ItemError(output_aspect=output_aspect, value=str(value)))
    else:
        for item in aspect.items:
            if item.value == value or item.text == value:
                return {VALUE: item.value, TEXT: item.text}, None, None  # todo exceptional value?
        #  logger.debug(f"could not find value: {value} in items: {[item.dict(exclude_none=True)
        #  for item in aspect.items]}")
        if isinstance(output_aspect.mapping_definition, AspectMappingDefinitionExceptionalValue):
            exceptional_definition: AspectMappingDefinitionExceptionalValue = output_aspect.mapping_definition
            return None, (exceptional_definition, value), None

        return (aspect_default(output_aspect.aspect) if use_default else None,
                None,  # todo exceptional value?
                ItemError(output_aspect=output_aspect, value=str(value)))


def vertical_reading(rows: Iterable[Dict[str, str]], id_cols: List[str], value_cols: List[str], as_lists=False) -> \
        Union[Dict[str, List[Dict[str, Any]]], Dict[str, List[List[Any]]]]:
    """
    reads rows vertically and returns a dict with the id as key and the values as list of dicts
    this should be used for deeper nestings deeper (e.g. lists in lists), multiselects in lists.
    """
    id_value_map: Dict[str, Union[Dict, List]] = {}

    def recursive_assign(row):
        current_sel = id_value_map
        for id_index, id_col in enumerate(id_cols):
            id_ = row[id_col]
            if id_index < len(id_cols) - 1:
                current_sel = current_sel.setdefault(id_, {})
            else:
                current_sel = current_sel.setdefault(id_, [])

        if as_lists:
            current_sel.append([row[value_col] for value_col in value_cols])
        else:
            current_sel.append({value_col: row[value_col] for value_col in value_cols})

    for row in rows:
        recursive_assign(row)
    return id_value_map


def vertical_reading2(rows: Iterable[Dict[str, str]], id_cols: List[str], value_cols: List[List[str]]) -> \
        Union[Dict[str, List[Dict[str, Any]]], Dict[str, List[List[Any]]]]:
    """
    reads rows vertically and returns a dict with the id as key and the values as list of dicts
    this should be used for deeper nestings deeper (e.g. lists in lists), multiselects in lists.
    This takes a list of value coluymns. The length should be as length of id_cols + 1. Values are inserted at corresponding
    levels
    """
    id_value_map: Dict[str, Union[Dict, List]] = {}

    def recursive_assign(row):
        current_sel = id_value_map
        for id_index, id_col in enumerate(id_cols):
            id_ = row[id_col]
            current_sel = current_sel.setdefault(id_, {})
            # print(id_, id_index, value_cols[id_index])
            for value_col in value_cols[id_index]:
                if (inter_val := current_sel.get(value_col)) is not None:
                    if inter_val != row[value_col]:
                        ValueError(f"inter-value should be the same: {inter_val}, {row[value_col]}")
                else:
                    current_sel[value_col] = row[value_col]
        for value_col in value_cols[-1]:
            current_sel.setdefault(value_col, []).append(row[value_col])

    for row in rows:
        recursive_assign(row)
    return id_value_map
