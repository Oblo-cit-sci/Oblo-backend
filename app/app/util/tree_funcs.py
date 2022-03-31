import csv
import json
import os
from copy import deepcopy, copy
from csv import DictWriter
from pathlib import Path
from typing import Callable, List, Dict, Optional, Tuple, Union, Any

from fastapi import UploadFile

from app.models.schema.aspect_models import AspectBaseIn, AspectMerge
from app.util.consts import VALUE, TEXT, DESCRIPTION
from app.util.files import dict_reader_guess_delimiter
from app.util.tree.tree import Tree

base_fields = [VALUE, "icon", "tag", "children", "extra"]
lang_fields = [TEXT, "description"]

CHILDREN = "children"


def recursive_transform(
        root: dict, func: Callable[[Dict, List[Dict], List[int], Any], Optional[bool]],
        ignore_root: bool = False,
        **kwargs
) -> dict:
    new_root = deepcopy(root)

    # noinspection PyDefaultArgument
    def rec_handle(node: dict, parents: List[dict] = [], indices: List[int] = [], **kwargs) -> Optional[bool]:
        if not ignore_root or parents:
            # noinspection PyArgumentList
            cancel = func(node, parents, indices, **kwargs)
            if cancel:
                return True
        for index, child in enumerate(node.get(CHILDREN, [])):
            cancel = rec_handle(child, parents + [node], indices + [index], **kwargs)
            if cancel:
                return True
    rec_handle(new_root, **kwargs)
    return new_root


# noinspection PyDefaultArgument
def all_attr_keys(node: dict, exclude: List[str] = []) -> List[str]:
    return list(filter(lambda k: k != CHILDREN and k not in exclude, node.keys()))


def check_unique_values(
        tree, check_keys: List[str], ignore_empty: bool = True
) -> Dict[str, List[str]]:  # only_on_level = False,

    values = {k: set() for k in check_keys}  # key: key, value: set
    duplicates = {k: [] for k in check_keys}

    def check_unique(node: dict, parents, **kwargs):
        # print(kwargs)
        for key in check_keys:
            value = node.get(key)
            if not value and ignore_empty:
                continue
            if value in kwargs["values"][key]:
                kwargs["duplicates"][key].append(value)
            kwargs["values"][key].add(value)

    # WOULD NEED indices
    recursive_transform(tree, check_unique, values=values, duplicates=duplicates)
    return duplicates


def flatten(tree: dict, keys: List[str], ignore_empty: bool = True) -> List[List]:
    all_nodes = []

    def collect(node, parents, **kwargs):
        res = []
        for k in keys:
            val = node.get(k)
            if val is None and kwargs["ignore_empty"]:
                continue
            res.append(val)
        kwargs["all_nodes"].append(res)

    # WOULD NEED indices
    recursive_transform(
        tree, collect, True, all_nodes=all_nodes, ignore_empty=ignore_empty
    )
    return all_nodes


# noinspection PyDefaultArgument
def get_by_index(root, indices=[]):
    act = root
    for ind in indices:
        act = act.get(CHILDREN, [])[ind]
    return act


# noinspection PyDefaultArgument
def get_path(root, indices=[], include_root: bool = False):
    res = []
    act = root
    if include_root:
        res.append(act)
    for ind in indices:
        try:
            act = act.get(CHILDREN, [])[ind]
        except IndexError:
            print(f"{ind}, but max index: {len(act.get('children', []))}")
            raise
        res.append(act)

    res = deepcopy(res)
    for n in res:
        if CHILDREN in n:
            del n[CHILDREN]

    return res


def tree2csv(tree: dict, output_file_path: Optional[Path] = None,
             additional_columns_only_for_levels: List[str] = None,
             is_base_tree: bool = True) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    """
    Converts a tree to a csv file, keeping the tree structure.
    :param tree:
    :param additional_columns_only_for_levels:
    :param output_file_path:
    :param is_base_tree: defines if value,icon or text,description are used
    :return: if not written to a file: A tuple of the header (list(str) and the rows dict(str,str)
    """
    print(additional_columns_only_for_levels)
    main_column = VALUE if is_base_tree else TEXT
    additional_level_columns = ["icon"] if is_base_tree else [DESCRIPTION]

    levels = tree.get("levels")
    root = tree.get("root")
    assert levels and root
    # create a list of all levels and add the additional_level_columns for each level
    fieldnames = []
    main_col_names = []

    def additional_columns_for_level(cur_level: str) -> bool:
        # empty list: additional_columns_only_for_levels means we dont have any additional columns
        return additional_columns_only_for_levels is None or cur_level in additional_columns_only_for_levels

    for level in levels:
        col = level.get(main_column)
        fieldnames.append(col)
        main_col_names.append(col)
        # if we use additional_columns_only_for_levels, we check if the current level is in the list
        if additional_columns_for_level(col):
            for column in additional_level_columns:
                fieldnames.append(f"{col}/{column}")

    def generate_rows(node: dict, parents: List[dict] = (), indices: List = (), **kwargs):
        level = len(indices) - 1
        # print("---")
        # print(node["value"])
        # print("kw-current", kwargs["current_row"])
        # todo validate if enough levels are provided (tree depth corresponds to the the number of levels)
        main_col_name = main_col_names[level]
        # ignore root
        if level >= 0:
            kwargs["current_row"][main_col_name] = node.get(main_column)
            if additional_columns_for_level(main_col_name):
                kwargs["current_row"].update({
                    **{f"{main_col_name}/{col}": node.get(col) for col in additional_level_columns}
                })
            if not node.get(CHILDREN):
                kwargs["rows"].append(copy(kwargs["current_row"]))
                kwargs["current_row"].clear()

    rows: List[dict] = []
    current_row = {}
    # WOULD NEED indices
    recursive_transform(root, generate_rows, rows=rows, current_row=current_row)
    if output_file_path:
        with open(output_file_path, "w", encoding="utf-8") as output:
            writer = DictWriter(output, fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        return fieldnames, rows


def table2tree(csv_file: UploadFile,
               *,
               as_base: bool = True,
               destination: Optional[str] = None,
               delim: Optional[str] = None,
               include_columns: Optional[list] = (),
               ignore_columns: Optional[list] = (),
               remove_empty_children: bool = True,
               root_value: str = None,
               read_levels: bool = True):
    """
    @param csv_file:
    @param as_base: makes content either `value` or if set false, `text` (language entries)
    @param destination: json file. if None generate Tree object and return
    @param delim: use csv-table delimiter. If None (default) try and guess (",",";")
    @param include_columns:
    @param ignore_columns:
    @param remove_empty_children:
    @param root_value: value/text for root element
    @param read_levels: reads 2nd row as level-fields (value or text), default: True
    @return:
    """
    if not delim:
        reader = dict_reader_guess_delimiter(csv_file)
    else:
        reader = csv.DictReader(csv_file.file, delimiter=delim)

    all_field_names = reader.fieldnames
    # print(all_field_names)
    VALUE = "value"

    if include_columns:
        field_names = include_columns
        missing = list(filter(lambda col: col not in all_field_names, include_columns))
        if missing:
            print("defined columns do not exist in the table", missing)
            print("candidates are", all_field_names)
            return None

    else:
        field_names = list(filter(lambda fn: "/" not in fn and fn not in ignore_columns, all_field_names))
    # logger.debug(f"Taking columns: {field_names}")
    # print(f"Taking columns: {field_names}")

    columns_act = {col: None for col in field_names}
    basename = os.path.basename(csv_file).split(".")[0]
    root_value = root_value if root_value else basename
    root = {CHILDREN: [], VALUE if as_base else TEXT: root_value}
    values = {"root": root}  # levels come later for language
    if as_base:
        values["levels"] = [{VALUE: field} for field in field_names]

    additional_data_rows = ["description", "icon"]

    def add_at_index(index: int, value, additional_data: Dict, tag: str, row: Dict):
        act = root[CHILDREN]
        # print(f"{value} -> {index}")
        for i in range(index):
            try:
                act = act[-1][CHILDREN]
            except:
                print(f"failed to insert {value} at index {i}. 'act' is {act}")
        # print(json.dumps(root, indent=2))
        # print(i)
        if as_base:
            insert = {VALUE: value}
        else:
            insert = {TEXT: value}
        for additional_k, val in additional_data.items():
            insert[additional_k] = val

        if tag and as_base:
            insert["tag"] = tag

        # only at the last level
        if row.get("extra-type") and row.get("extra-name") and (index == len(field_names) - 1):
            if as_base:
                insert["extra"] = {"type": row["extra-type"], VALUE: row["extra-name"]}
            else:
                insert["extra"] = {TEXT: row["extra-name"]}

        # print(description)
        if index < len(field_names) - 1:
            # print("+kids", index, value)
            insert[CHILDREN] = []
        # print(insert)
        act.append(insert)

    if read_levels:
        levels = next(reader)
    if not as_base:
        values["levels"] = [{"text": levels[field], "description": levels[field + "/description"]} for field in
                            field_names]
    for row in reader:
        all_levels_of_row = [row[col].strip() for col in field_names if row[col].strip() != ""]

        for index, col in enumerate(field_names):
            val = row[col]
            # print(val, columns_act)
            if val != columns_act[col] and val.strip() != "":
                columns_act[col] = val
                # print("got col", col)
                for col_name in field_names[field_names.index(col) + 1:]:
                    # print("resetting", col_name)
                    columns_act[col_name] = None
                # here also reset the columns_act of the following columns. so when the same name appears (in one of the following cols)
                # they are accepts (val != columns_act[col] must pass)
                additional_data = {}
                for additionals in additional_data_rows:
                    if additionals in (base_fields if as_base else lang_fields):
                        col_name = f"{col}/{additionals}"
                        # print(col_name)
                        if col_name in all_field_names:
                            # print("found")
                            additional_data[additionals] = row[col_name]

                tag = None
                # print(val, val == all_levels_of_row[-1], row.get("tag"))
                if val == all_levels_of_row[-1]:  # leafnode
                    tag = row.get("tag")
                # print(val)
                # print("additionals", additional_data)
                add_at_index(index, val.strip(), additional_data, tag, row)

    if remove_empty_children:
        def rec_kids_search(node):
            if CHILDREN in node:
                if len(node[CHILDREN]) == 0:
                    del node[CHILDREN]
                else:
                    for kid in node[CHILDREN]:
                        rec_kids_search(kid)

        rec_kids_search(root)

    # print(values)
    tree = Tree.from_dict(values)
    if destination:
        json.dump(tree.dumps(), open(destination, "w", encoding="utf-8"))
    return tree


# def convert_tree_to_lang_version(tree: dict):
#     def rec_convert(node: dict):
#         node["text"] = node["value"]
#         del node["value"]
#         for kid in node.get(CHILDREN, []):
#             rec_convert(kid)
#
#     lang_tree = {**tree}
#     for level in lang_tree.get("levels"):
#         level["text"] = level["value"]
#         del level["value"]
#
#     rec_convert(lang_tree["root"])
#
#     return lang_tree
#
#
# def rec_tree_value_length_check(tree, max_value_len=64):
#     def rec_validate_node(node, parents=[]):
#         value = node["value"]
#         v_len = len(value)
#         if v_len > max_value_len:
#             print(f"node value too long '{value}' ({v_len})\n@ {parents}")
#         for kid in node.get(CHILDREN, []):
#             rec_validate_node(kid, parents + [value])
#     rec_validate_node(tree["root"])


def tree_aspect_values(nodes, include_icon: Optional[bool] = True) -> List[Dict[str, str]]:
    result = []
    for node in nodes:
        value = {
            VALUE: node[VALUE],
            TEXT: node[TEXT]
        }
        if icon := node.get("icon") and include_icon:
            value["icon"] = icon
        result.append(value)
    return result


def find_by(tree, value_text, use_value=True, use_text=True) -> Tuple[List[Dict[str, str]], Optional[bool]]:
    result = {"result": [], "last_has_children": None}
    node_found = {"found": False}

    def find(node, parents, indices, **kwargs) -> Optional[bool]:
        """
        returns true when found
        """
        found_here = False
        if kwargs["use_value"] and node["value"] == value_text:
            kwargs["node_found"]["found"] = True
            found_here = True
        if kwargs["use_text"] and node["text"] == value_text:
            kwargs["node_found"]["found"] = True
            found_here = True
        if found_here:
            kwargs["result"]["result"] = tree_aspect_values(parents[1:] + [node])
            # returning this is important to validate if the value is valid.
            # if no allow_select_levels is not specified only leaf nodes are allowed to be selected
            kwargs["result"]["last_has_children"] = node.get(CHILDREN, []) is not []
            return True
    recursive_transform(
        tree, find, True, use_value=use_value, use_text=use_text, node_found=node_found, result=result
    )
    return result["result"], result["last_has_children"]


def convert_level_names_to_indices(tree: dict, levels: List[Union[int, str]]) -> List[int]:
    """
    converts a list of int,str levels into a list of int levels
    """
    tree_levels = [level["value"] for level in tree["levels"]]
    level_indices = []
    for level in levels:
        if isinstance(level, int):
            level_indices.append(level)
        else:
            level_indices.append(tree_levels.index(level))
    return level_indices


def validate_value(tree: dict, value: List[dict], aspect: Union[AspectBaseIn, AspectMerge], strict_language=False,
                   allow_unset: bool = False) -> \
        Tuple[bool, Optional[str]]:
    """
    validate a value against a tree. Checks if value match (also text if strict_language is True)
    and if the node is allowed to be selected.
    @returns: True, or False with a message
    # todo tree could also be valuesMerge
    """
    if not allow_unset and not value:
        return False, "UNSET VALUE"
    if aspect.attr:
        if aspect.attr.allow_select_levels:
            allow_select_levels = convert_level_names_to_indices(tree, aspect.attr.allow_select_levels)
            if len(value) not in allow_select_levels:
                return False, "LEVEL_NOT_ALLOWED"
    current_node = tree["root"]
    for level_value in value:
        next_node_found = False
        for child in current_node.get(CHILDREN, []):
            if child[VALUE] == level_value[VALUE] and (not strict_language or child[TEXT] == level_value[TEXT]):
                current_node = child
                next_node_found = True
                break
        if not next_node_found:
            if strict_language:
                child_values = tree_aspect_values(current_node, include_icon=False)
                return False, f"LEVEL/TEXT DONT MATCH: {child_values}, value: {level_value}"
            else:
                return False, f"VALUE_NOT_FOUND: {[node[VALUE] for node in current_node]}, value: {level_value}"
    return True, None
