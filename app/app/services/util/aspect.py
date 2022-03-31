from logging import getLogger
from typing import Any, List

from jsonpath import jsonpath

from app.models.orm import Entry
from app.models.schema.aspect_models import AspectMerge
from app.util.consts import COMPOSITE, LIST, STR, MULTISELECT, TREE, IMAGES, VALUE

TYPE = "type"

LOCATION = "location"

VALUE = "value"

logger = getLogger(__name__)


# TODO needs to recursive!!!
def get_aspect_of_type(entry: Entry, type_s: str) -> List[str]:
    if not entry.template:
        logger.warning(f"Entry has no template. maybe its one itself. {Entry}")
        return []
    aspects = entry.template.aspects
    type_names = [a["name"] for a in aspects if a[TYPE] == type_s]
    return type_names


def find_references(template: Entry):
    pass


"""
export function resolve_tags(entry, template) {
  // console.log(entry, template)
  let tags = []
  for (let aspect of template.aspects) {
    tags = tags.concat(resolve_tag(entry.values[aspect.name], aspect))
  }
  return tags.reduce((groups, tag_val) => {
    if (groups.hasOwnProperty(tag_val.name)) {
      groups[tag_val.name].push(tag_val.value)
    } else {
      groups[tag_val.name] = [tag_val.value]
    }
    return groups
  }, {})
}

function resolve_tag(aspect_value, aspect) {
  // console.log("resolve_tag", aspect_value, aspect.name)
  let res = []
  const tag = attr(aspect).tag
  if (tag) {
    // debugger
    if (Array.isArray(tag)) {
      for (let tag_option of tag) {
        const tag_val = resolve_from_value(aspect_value, tag_option)
        if (tag_val) {
          res.push(tag_val)
          break
        }
      }
    } else {
      const tag_val = resolve_from_value(aspect_value, tag)
      if (tag_val)
        res.push(tag_val)
    }
  }
  if (aspect.type === COMPOSITE) {
    for (let component of aspect.components) {
      res = res.concat(resolve_tag(aspect_value.value[component.name], component))
    }
  } else if (aspect.type === LIST) {
    for (let list_item of aspect_value.value) {
      res = res.concat(resolve_tag(list_item, aspect.list_items))
    }
  }
  return res
}

function resolve_from_value(aspect_value, tag) {
  const value = jp.value(aspect_value, tag.subpath)
  if (value) {
    return {name: tag.name, value}
  }
}
"""


# def resolve_tags(entry_data: dict, template: dict):
#     """
#     @param entry_data:
#     @return:
#     """
#     tags = []
#     for aspect in template["aspects"]:
#         tags.extend(resolve_tag(entry_data["values"][aspect["name"]], aspect))
#     result = {}
#     for tag in tags:
#         # todo can probably do it with a setdefault
#         if tag["name"] in result:
#             result[tag["name"]].append(tag["value"])
#         else:
#             result[tag["name"]] = tag["value"]
#     return result


# def resolve_tag(aspect_value: dict, aspect: dict) -> List:
#     """
#     @param aspect_value:
#     @param aspect:
#     @return:
#     """
#     res = []
#     if tag := aspect.get("tag"):
#         if isinstance(tag, list):
#             for tag_option in tag:
#                 tag_val = resolve_from_value(aspect_value, tag_option)
#                 if tag_val:
#                     res.append(tag_val)
#                     break
#         else:
#             tag_val = resolve_from_value(aspect_value, tag)
#             if tag_val:
#                 res.append(tag_val)
#     if aspect["type"] == COMPOSITE:
#         for component in aspect[COMPONENTS]:
#             res.extend(resolve_tag(aspect_value["value"][component.name], component))
#     elif aspect["type"] == LIST:
#         for list_item in aspect_value[VALUE]:
#             res.extend(resolve_tag(list_item, aspect["list_item"]))
#     return res


def resolve_from_value(aspect_value: dict, tag: dict) -> Any:
    value = jsonpath(aspect_value, tag["subpath"])
    if value:
        return {"name": tag["name"], value: value}


def aspect_raw_default_value(aspect: dict):
    aspect_type = aspect["type"]
    if aspect_type == STR:
        return ""
    elif aspect_type in [LIST, IMAGES, TREE, MULTISELECT]:
        return []
    elif aspect_type == COMPOSITE:
        return {
            comp["name"]: aspect_default_value(comp) for comp in aspect["components"]
        }
    else:
        return None


def aspect_default_value(aspect: dict):
    return {"value": aspect_raw_default_value(aspect)}


class Unpacker:
    """
    class to help unpacking values if needed and repacking if that was the original form
    """

    def __init__(self, value):
        """
        packed or unpacked...
        """
        if VALUE in value:
            self.is_packed = True
            self.raw_value = value[VALUE]
        else:
            self.raw_value = value

    def get_unpacked(self):
        return self.raw_value

    def pack(self, value) -> Any:
        if self.is_packed:
            return {VALUE: value}
        else:
            return value


def raw_aspect_default(aspect: AspectMerge):
    aspect_type = aspect.type
    if aspect_type == STR:
        return ""
    elif aspect_type in [LIST, IMAGES, TREE, MULTISELECT]:
        return []
    elif aspect_type == COMPOSITE:
        result = {}
        for sub_aspect in aspect.comment:
            result[sub_aspect.name] = {VALUE: aspect_default(sub_aspect)}
        return result
    else:
        # todo could have an additional assert...
        return None


def aspect_default(aspect: AspectMerge):
    return {VALUE: raw_aspect_default(aspect)}

    # HEAD = "head"
    # INT = "int"
    # FLOAT = "float"
    # SELECT = "select"
    # # ENTRYLIST = "entrylist"
    # DATE = "date"
    # TREEMULTISELECT = "treemultiselect"
    # # LOCATION = "location"
    # COMPOSITE = "composite"
    # OPTIONS = "options"
    # ENTRYLINK = "entrylink"
    # ENTRY_ROLES = "entry_roles"
    # EXTERNAL_ACCOUNT = "external_account"
    # VIDEO = "video"
    # GEOMETRY = "geometry"
    # MONTH = "month"

    # elif aspect_type == [LOCATION]:
    #   return False
    # case COMPOSITE:
    #   let res = {}
    #   if (!aspect) {
    #     console.log("aspect default value of composites needs the whole aspect passed")
    #     return res
    #   }
    #   aspect.components.forEach(c => {
    #     res[c.name] = {value: aspect_raw_default_value(c)} //packed_aspect_default_value(c, {name: c.name})
    #   })
    #   return res
    # case HEAD:
    # case :
    # case SELECT:
    # case OPTIONS:
    # case TREEMULTISELECT:
    # case DATE:
    # // todo could also check attr.min
    # case INT:
    # case FLOAT:
    # case ENTRYLINK:
    # case ENTRY_ROLES:
    # case EXTERNAL_ACCOUNT:
    # case VIDEO:
    # case GEOMETRY:
    # case MONTH:
    #   return null
    # //return ld.map(aspect.components, (c) => [c.name, packed_aspect_default_value(c, {name: c.name})]))
    # default:
    #   console.log("Warning trying to ge default value of aspect-type of unknown type", aspect)
    #   console.trace()
    #   return null


def pack_raw_value(value: Any) -> dict[str, Any]:
    return {VALUE: value}