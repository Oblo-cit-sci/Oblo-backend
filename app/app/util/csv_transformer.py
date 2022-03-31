from csv import DictWriter
from datetime import datetime
from typing import List

from app.models.orm import Entry
from app.util.consts import TYPE, NAME, TERMINAL_ASPECT_TYPES, VALUE

regular_entry_base_meta_columns = [
    "uuid",
    "creation_ts",
    "domain",
    "template",
    "template_version",
    "type",
    "last_edit_ts",
    "version",
    "title",
    "status",
    "description",
    "language",
    "privacy",
    "license",
    "image",
    "attached_files",
    "actors",
]

straight_grab = [
    "uuid",
    "creation_ts",
    "domain",
    "template_version",
    "type",
    "last_edit_ts",
    "version",
    "title",
    "status",
    "description",
    "language",
    "privacy",
    "license",
    "image",
    "template_version",
]

list_item_sep = "|"
inner_value_sep = ":"

transformer = {
    "uuid": lambda uuid: str(uuid),
    "creation_ts": lambda ts: datetime.strftime(ts, "%Y"),
    "last_edit_ts": lambda ts: datetime.strftime(ts, "%Y"),
    "template": lambda template: template.title,
    "actors": lambda actors: cell_separated(
        list(map(lambda entry_role: entry_role.csv_format(inner_value_sep), actors))
    ),
}


def cell_separated(values: List[str]):
    return list_item_sep.join(values)


def transform_to_csv(entry: Entry, template: Entry):
    res = {}
    print(
        cell_separated(
            list(
                map(
                    lambda entry_role: entry_role.csv_format(inner_value_sep),
                    entry.actors,
                )
            )
        )
    )

    for col in regular_entry_base_meta_columns:
        # if col in straight_grab:
        val = getattr(entry, col)
        if not val:
            val = ""
        if col in transformer:
            val = transformer[col](val)
        res[col] = val

    # temp file method. doesnt work atm
    # fp = tempfile.TemporaryFile()
    # bh = list(map(lambda v: v.encode("utf-8"), regular_entry_base_meta_columns))

    no_t = open("t.csv", "w")

    writer = DictWriter(no_t, regular_entry_base_meta_columns)
    # print(bh)
    # print(writer.fieldnames)
    writer.writeheader()
    writer.writerow(res)

    no_t.close()
    csv_text = open("t.csv").read()

    # temp file method...
    # fp.seek(0)
    # csv_text = fp.read()

    for aspect in template.aspects:
        res = resolve_values(aspect, entry.values[aspect.name])
    return csv_text


def resolve_values(aspect, value):
    a_name = aspect.get(NAME)
    a_type = aspect[TYPE]

    if a_type in TERMINAL_ASPECT_TYPES:
        return {a_name: value[VALUE]}
