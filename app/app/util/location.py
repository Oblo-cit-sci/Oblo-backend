from logging import getLogger
from typing import Union, Dict

from app.models.orm import Entry, RegisteredActor
from app.models.schema import EntryMeta, MapEntry

logger = getLogger(__name__)


def set_visible_location(
    entry: Union[EntryMeta, MapEntry, Dict], db_obj: Entry, actor: RegisteredActor
):
    if db_obj.location and not db_obj.protected_read_access(actor):
        new_loc = []
        for loc in db_obj.location:
            new_loc.append(only_public_location(loc))
        # print(entry.location)
        if type(entry) == dict:
            entry["location"] = new_loc
        else:
            entry.location = new_loc


def only_public_location(location_data: dict) -> dict:
    if "public_loc" in location_data:
        return location_data["public_loc"]
    else:
        return location_data
