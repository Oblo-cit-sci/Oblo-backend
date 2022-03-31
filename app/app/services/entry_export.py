from collections import namedtuple
from logging import getLogger
from types import GeneratorType
from typing import List, Dict, Union, Iterable
from urllib.parse import urlunparse, urlparse, urlencode

from jsonpath import jsonpath

from app.settings import env_settings
from app.util.consts import (
    COMPOSITE,
    COMPONENTS,
    LIST,
    TYPE,
    STR,
    VALUE,
    SELECT,
    MULTISELECT,
    LOCATION,
    NAME,
    IMAGES,
    UUID,
    LIST_ITEMS,
    TREE,
    TITLE,
    LANGUAGE,
    ACTORS,
    STATUS,
    PRIVACY,
    LICENSE,
    VERSION,
    TEMPLATE,
    TEMPLATE_VERSION,
    IMAGE,
    INT,
    FLOAT,
    RULES,
    LOCATION_ASPECT,
)

value_result = namedtuple("value_result", ["name", "value"])

INTERNAL_SEPARATOR = ";"  # multiselect, tree, location
LISTITEM_SEPARATOR = "|"
MISSING_SELECT_CHAR = "---"
MISSING_VALUE = "---"

logger = getLogger(__name__)

config = {
    "include_select_texts": True,
    "aspect_titles": True,
    "default_meta": [
        UUID,
        TITLE,
        LANGUAGE,
        ACTORS,
        STATUS,
        PRIVACY,
        LICENSE,
        "creation_ts",
        VERSION,
        "tags",
        "last_edit_ts",
        TEMPLATE,
        TEMPLATE_VERSION,
        LOCATION,
        IMAGE,
    ],
}

location_aspect_data_descr = {
    "place_name": "place_name",
    "lon": "coordinates.lon",
    "lat": "coordinates.lat",
    "precision": "location_precision",
    "public_precision": "public_precision",
    "public_place_name": "public_loc.place_name",
    "public_lon": "public_loc.coordinates.lon",
    "public_lat": "public_loc.coordinates.lat",
}


def entry_meta_columns(template: dict) -> List[str]:
    columns: List[str] = config["default_meta"] + ["url"]
    # dont add any location columns if no LOCATION_ASPECT
    if "location" in columns and template[RULES].get(LOCATION_ASPECT):
        columns.remove("location")
        columns.extend(location_aspect_data_descr.keys())
    return columns


def column_names(template: dict, meta_only: bool) -> List[str]:
    columns: List[str] = entry_meta_columns(template)
    if meta_only:
        return columns

    aspects = template["aspects"]

    def recursive_aspect_name(aspect: dict, parent_aspects: List[Dict] = ()):
        aspect_type = aspect["type"]
        if aspect_type in {
            "str",
            "int",
            "float",
            "select",
            "multiselect",
            "tree",
            "images",
        }:
            yield get_aspect_column_name(aspect, parent_aspects)
        if aspect_type == LOCATION:
            for key in location_aspect_data_descr.keys():
                yield f"{get_aspect_column_name(aspect, parent_aspects)}.{key}"
        if aspect_type == COMPOSITE:
            for component in aspect[COMPONENTS]:
                for col_name in recursive_aspect_name(
                    component, [*parent_aspects, aspect]
                ):
                    yield col_name
        if aspect_type == LIST:
            for col_name in recursive_aspect_name(
                aspect["list_items"], [*parent_aspects, aspect]
            ):
                yield col_name

    for aspect in aspects:
        for column_name in recursive_aspect_name(aspect):
            columns.append(column_name)
    return columns


def process_entry(entry: dict, template: dict, meta_only: bool) -> dict:
    result = process_entry_metadata(entry, template)
    if not meta_only:
        result = {**result, **process_entry_values(entry, template)}
    return result


def process_entry_metadata(entry: dict, template: dict):
    result = {}
    for meta_val in config["default_meta"]:
        # needs to be skipped here, when there is no LOCATION_ASPECT, the entry will not have it, and we
        # dont want it to write: MISSING_VALUE
        if meta_val == LOCATION and not template[RULES].get(LOCATION_ASPECT):
            continue
        if entry.get(meta_val):
            if meta_val == "actors":
                value = simple_join(
                    [
                        f"{entry_actor['actor']['registered_name']}:{entry_actor['role']}"
                        for entry_actor in entry[meta_val]
                    ],
                    INTERNAL_SEPARATOR,
                )
            elif meta_val == LOCATION:
                if template[RULES].get(LOCATION_ASPECT):
                    # todo or rather than checkin ig there is a locationAspect make em empty...
                    value = aspect_list_data(
                        entry[meta_val], location_aspect_data_descr, INTERNAL_SEPARATOR
                    )
                else:  # skip it so we dont add MISSING_VALUE: "---"
                    continue
            elif meta_val == "template":
                value = entry["template"]["slug"]
            elif meta_val == "image":
                value = file_url(entry["uuid"], entry["image"])
            # elif meta_val == "attached_files":
            #     value = simple_join([file_url(entry["uuid"], url) for url in entry["attached_files"]])
            elif meta_val == "tags":
                value = simple_join(
                    [
                        f"{group}:{', '.join(tags)}"
                        for (group, tags) in entry[meta_val].items()
                    ],
                    INTERNAL_SEPARATOR,
                )
            else:
                value = entry[meta_val]
        else:
            logger.debug(f"meta aspect missing: {meta_val}")
            value = MISSING_VALUE
            # logger.warning("meta aspect missing")
        if type(value) == dict:
            result = {**result, **value}
        else:
            result[meta_val] = value
    # ADDITIONAL:
    result["url"] = urlunparse(
        urlparse(env_settings().HOST)
        ._replace(path="domain")
        ._replace(query=urlencode({"entry_mode": "view", "uuid": entry["uuid"]}))
    )
    return result


def get_aspect_column_name(aspect: dict, parent_aspects: List[Dict] = ()) -> str:
    key = "name"
    if config["aspect_titles"]:
        key = "label"
        if not aspect.get(key):
            logger.error(
                f"Broken aspect description. label missing for {aspect['name']}"
            )
            key = "name"
    return ".".join([aspect[key], *(p[key] for p in parent_aspects)])


def process_entry_values(entry, template) -> dict:
    aspects = template["aspects"]
    values = entry["values"]

    def get_select_value(value: dict) -> str:
        if not value["value"]:
            return MISSING_SELECT_CHAR
        if config["include_select_texts"]:
            return f"{value['value']}:{value['text']}"
        else:
            return value["value"]

    def get_multiselect_value_HACK(value: dict, aspect: dict):
        """
        we have to use this for "include_select_texts" cuz the value actually doesnt store the texts
        so we have to look them up in the aspect.
        transform it to how it should be
        """

        def lookup_text(value):
            try:
                return next(filter(lambda i: i["value"] == value, aspect["items"]))[
                    "text"
                ]
            except:
                logger.warning(
                    f"get_multiselect_value_HACK: no text for value: {value}"
                )
                return ""

        if config["include_select_texts"]:
            return [{"value": v, "text": lookup_text(v)} for v in value["value"]]
        else:
            return [{"value": v} for v in value["value"]]

    def unpack_nested_results(result):
        if type(result) == value_result:
            yield result
        if type(result) == GeneratorType:
            for item in result:
                for item_result in unpack_nested_results(item):
                    yield item_result

    def process_aspect_value(
        value: dict, aspect: dict, parent_aspects: List[Dict] = ()
    ) -> Iterable[value_result]:
        name = get_aspect_column_name(aspect, parent_aspects)
        result_value = None
        aspect_type = aspect[TYPE]
        logger.warning(f"{name}: {aspect_type}")
        if aspect_type in [STR, INT, FLOAT]:
            result_value = value[VALUE]
        elif aspect_type == SELECT:
            result_value = get_select_value(value)
        elif aspect_type == MULTISELECT:
            # todo this is how it should be, but currently it just saves the value strings
            # result_value = simple_join([get_select_value(v) for v in value["value"]])
            result_value = simple_join(
                [
                    get_select_value(v)
                    for v in get_multiselect_value_HACK(value, aspect)
                ],
                INTERNAL_SEPARATOR,
            )
        elif aspect_type == TREE:
            # todo should merge with multiselect
            result_value = simple_join(
                [get_select_value(v) for v in value[VALUE]], INTERNAL_SEPARATOR
            )
        elif aspect_type == LOCATION:
            result_data = aspect_data(value[VALUE], location_aspect_data_descr)
            for k, v in result_data.items():
                yield value_result(f"{name}.{k}", v)
        elif aspect_type == COMPOSITE:
            new_parents = [*parent_aspects, aspect]
            for component in aspect[COMPONENTS]:
                component_value = value[VALUE].get(component[NAME])
                for res in process_aspect_value(
                    component_value, component, new_parents
                ):
                    yield res
        elif aspect_type == LIST:
            new_parents = [*parent_aspects, aspect]
            unpacked_results = []
            for item_value in value[VALUE]:
                item_result = process_aspect_value(
                    item_value, aspect[LIST_ITEMS], new_parents
                )
                # unpack the results, which could also be of type composite or lists, ...
                for result in unpack_nested_results(item_result):
                    unpacked_results.append(result)
            # group all unpackked results by their aspect-name
            list_results = {}
            for res in unpacked_results:
                list_results.setdefault(res.name, []).append(res.value)
            # if there are nested lists we use a different number of separators
            # create value-result tuples using the right number
            nested_list_level = (
                len(list(filter(lambda aspect: aspect[TYPE] == LIST, parent_aspects)))
                + 1
            )
            seperator = f" {nested_list_level * LISTITEM_SEPARATOR} "
            # yield individual columns back
            for name, values in list_results.items():
                yield value_result(name, seperator.join(values))
        elif aspect_type == IMAGES:
            result_value = simple_join(
                [file_url(entry[UUID], img["file_uuid"]) for img in value[VALUE]],
                INTERNAL_SEPARATOR,
            )
        else:
            print(f"unknown aspect type: {aspect[NAME]} : {aspect_type}, :: {value}")
            yield None

        if result_value:
            yield value_result(name, result_value)

    result = {}
    for aspect in aspects:
        value = values.get(aspect[NAME])
        if not value:
            logger.warning(f"Value missing in {entry[UUID]}: {aspect[NAME]}")
        try:
            aspect_result = process_aspect_value(value, aspect)
            for res in aspect_result:
                if res:
                    result[res.name] = res.value
        except Exception:
            logger.warning(f"Invalid result for {aspect[NAME]}")
            continue
    return result


def join_list(
    list_result: List[Dict], seperator: str
) -> Dict[str, Union[str, int, float]]:
    result = {}
    for d in list_result:
        for k, v in d.items():
            result.setdefault(k, []).append(str(v))
    for k, v in result.items():
        result[k] = seperator.join(v)
    return result


def aspect_list_data(
    data: dict, descr: dict, separator: str
) -> Dict[str, Union[str, int, float]]:
    return join_list([aspect_data(d, descr) for d in data], separator)


def simple_join(data: List[str], separator: str) -> str:
    return separator.join(data)


def aspect_data(data, descr):
    """
    getting the data out of a complex aspect-value (so far only location) by using a descriptor dict.
    it contains keys (keys in the result) and jsonpath locations from where to grab the values...
    """
    result = {}
    for v, k in descr.items():
        value = jsonpath(data, k)
        if value:
            result[v] = value[0]
    return result


def file_url(entry_uuid: str, file_uuid: str):
    """
    for images
    """
    return urlunparse(
        urlparse(env_settings().HOST)._replace(
            path=f"api/entry/{entry_uuid}/attachment/{file_uuid}"
        )
    )
