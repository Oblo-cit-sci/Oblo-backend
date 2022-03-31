from logging import getLogger
from os.path import join
from typing import List

from app import settings
from app.models.orm import Entry
from app.services.service_worker import ServiceWorker

logger = getLogger(__name__)

DOMAINS_FOLDER = join(settings.INIT_DATA_FOLDER, "domains")


# def validate_entry_files(entry: Entry, folder: str):
#     """
#     NOT USED
# 	just a beginning, start with code-tree and list-
# 	todo make it more flexible regards the root name
# 	"""
#
#     def validate_item(data: Dict):
#         if type(data) == dict and "icon" in data:
#             if not isfile(join(folder, data["icon"])):
#                 logger.warning(
#                     f"an indicated icon is missing for {entry.title}, named: {data['icon']}"
#                 )
#
#     def rec_get_icon(node):
#         validate_item(node)
#         for kid in node.get("children", []):
#             rec_get_icon(kid)
#
#     if entry.template.slug == "value_tree":
#         rec_get_icon(entry.values["root"])
#     elif entry.template.slug == "value_list":
#         for val in entry.values["list"]:
#             validate_item(val)
#     else:
#         logger.warning("unknown template to check icons")


def get_license_entry(sw: ServiceWorker) -> Entry:
    return sw.template_codes.get_by_slug_lang("cc_licenses", "en")


def get_license_values(sw: ServiceWorker) -> List[str]:
    return [list_item["value"] for list_item in get_license_entry(sw).values["list"]]
