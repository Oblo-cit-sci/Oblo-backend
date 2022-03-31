from logging import getLogger
from typing import List, Set

from app.models.orm import Entry
from app.models.schema import EntrySearchQueryIn
from app.services.entry import entries_query_builder, get_file_path
from app.services.service_worker import ServiceWorker
from app.util.consts import VALUE, CODE, BASE_CODE, TEXT, CODE_SCHEMA
from app.util.tree_funcs import recursive_transform

logger = getLogger(__name__)


class CodeService:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    def create_tags(self, code_entry: Entry):
        """
        entries that can make tags from 2 types. from lists and from trees. generally they come from 'code' entries.
        the definition of how the tags are made comes from `rules.tags`
        there should be one of these 2 keys:
        `rules.tags.from_tree` or `rules.tags.from_list`
        for lists there needs to be a key 'values.list'
        for trees there needs to be a key  `rules.tags.from_tree.levels`
        """

    # if code_entry.rules and TAGS in code_entry.rules:
    # 	# print("******", code_entry.title)
    # 	tags = code_entry.rules[TAGS]
    # 	new_tags: List[Tag] = []
    # 	if "from_tree" in tags:
    # 		new_tags = create_tags_from_tree_entry(code_entry)
    # 	elif "from_list" in tags:
    # 		new_tags = self.root_sw.tag.resolve_from_list_code(code_entry)

    def get_tree_from_value(self, code_entry: Entry, value: str) -> List[str]:
        """
        returns back all upper levels of a given value
        @param code_entry:
        @param value:
        @return:
        """

        def rec_search(node: dict):
            if node[VALUE] == value:
                return [{VALUE: value}]
            for child in node.get("children", []):
                search_res = rec_search(child)
                if search_res:
                    return [{VALUE: value}] + search_res
            return None

        return rec_search(code_entry.values["root"])

    def get_tree_from_text(self, code_entry: Entry, text: str) -> List[str]:
        def rec_search(node: dict):
            if node[TEXT] == text:
                return [node]
            for child in node.get("children", []):
                search_res = rec_search(child)
                if search_res:
                    return [node] + search_res
            return None

        return rec_search(code_entry.values["root"])

    def get_language_entries(self) -> List[Entry]:
        query = entries_query_builder(
            self.root_sw,
            search_query=EntrySearchQueryIn(required=[]),
            entrytypes={BASE_CODE, CODE},
        ).filter(Entry.slug == "languages")
        return query.all()

    def validate_icons(self, code_entry: Entry) -> Set[str]:
        """
        checks if all icons are present in the public  folder
        @param code_entry:
        @return:
        """

        def get_icon(node: dict, parents, indices, **kwargs):
            if icon := node.get("icon"):
                kwargs["icons"].add(icon)

        code_schema = code_entry.rules[CODE_SCHEMA]
        folder_destination_slug = data_source if (data_source := code_entry.rules.get("data_source")) else code_entry.slug
        if code_schema:
            icons = set()
            if code_schema == "value_tree":
                tree = code_entry.values["root"]
                recursive_transform(tree, get_icon, icons=icons)
            elif code_schema == "value_list":
                list_ = code_entry.values["list"]
                icons = set(item["icon"] for item in list_ if item.get("icon"))
            else:
                pass
            missing = {
                icon for icon in icons
                if not bool(get_file_path(folder_destination_slug, icon))
            }
            if missing:
                logger.warning(f"Code-entry: Some files for '{code_entry.slug}' are missing: {missing}")
            return missing
        else:
            logger.warning("no code_schema")
