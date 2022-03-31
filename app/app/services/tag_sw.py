from logging import getLogger
from typing import List, Optional, Tuple, Dict

from sqlalchemy import or_, and_
from sqlalchemy.orm.attributes import flag_modified

from app.models.orm import Tag, Entry
from app.models.schema import TagData
from app.models.schema.template_code_entry_schema import TemplateMerge, ValuesMerge
from app.models.schema.aspect_models import ItemMerge
from app.models.schema.tag_schema import TagOut
from app.services.service_worker import ServiceWorker
from app.services.template_code_entry_sw import code_entry_validate_unique_values
from app.util.consts import CODE, VALUE_LIST, VALUE_TREE
from app.util.exceptions import ApplicationException

logger = getLogger(__name__)


class TagService:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    def crud_get(self, value: str):
        return self.db_session.query(Tag).filter(Tag.value == value).all()

    def get_all(self, values: List[str]):
        """
        @param values: get the tags for passed values
        @return:
        """
        # noinspection PyUnresolvedReferences
        return self.db_session.query(Tag).filter(Tag.value.in_(values)).all()

    def get_by_title(self, title: str, language: str) -> List[Tag]:
        return (
            self.db_session.query(Tag).filter(Tag.text[language].astext == title).all()
        )

    def get_all_by_titles(self, titles: List[str], language: str):
        return (
            self.db_session.query(Tag)
            .filter(Tag.text[language].astext.in_(titles))
            .all()
        )

    def get_from_slug(self, slug: str) -> List[Tag]:
        """
        gets all tags from a slug. this is used to extend tags, that already exist in a language
        @param slug:
        @return:
        """
        return list(self.db_session.query(Tag).filter(Tag.source_slug == slug).all())

    def udpate_from_entry(self, entry: TemplateMerge):
        """
        TODO is this not called from the insert?
        todo wrong type is passed
        @param entry:
        @return:
        """
        logger.debug(f"udpate_from_entry: Updating tag of entry: {entry}")

        tag_sw = self.root_sw.tag
        try:
            model_tags_data: List[TagData] = tag_sw.resolve_from_entry(entry)
        except ApplicationException as err:
            raise err

        unique_values = set(tag.value for tag in model_tags_data)
        if len(unique_values) != len(model_tags_data):
            logger.warning("Tags are not unique")
            for tag_value in unique_values:
                tags = list(filter(lambda tag: tag.value == tag_value, model_tags_data))
                if len(tags) > 1:
                    logger.warning(f"'{tag_value}' appears {len(tags)} times")
                    for t in tags:
                        model_tags_data.remove(t)

        language = entry.language

        # tags that exist already for the same e-slug
        db_tags: List[Tag] = self.get_from_slug(entry.slug)

        missing_in_db, missing_in_list, match = tag_sw.overlap(db_tags, model_tags_data)
        logger.debug(f"missing_in_db: {missing_in_db}")
        logger.debug(f"missing_in_list: {missing_in_list}")

        all_tags_value_tag_map = {t.value: t for t in db_tags}

        # contained, missing, tag_dict = tag_sw.overlap(existing_tags, tags)
        for tag_data in missing_in_db:
            tag = tag_sw.create_tag(tag_data, language, entry)
            tag.parent = all_tags_value_tag_map.get(tag_data.parent_value)
            self.db_session.add(tag)
        for tag_update_data in match:
            # todo wtf is going on here...
            tag = tag_update_data[0]
            tag_data = tag_update_data[1]
            existing_model = TagData(**tag.for_lang(language))
            if existing_model != tag_data:
                logger.info(f"changes in tag: {tag_data.value}")
                self.update_tag(tag, tag_data, language)
                tag.parent = all_tags_value_tag_map.get(tag_data.parent_value)
                self.db_session.add(tag)
        for o in missing_in_list:
            self.remove_tag(o, language)

        self.db_session.commit()

    def tags_out(self, tags: List[Tag], language: str):
        return [self.tag_out(t, language) for t in tags]

    def tag_out(self, tag: Tag, language: str):
        text = tag.text.get("language", "")
        description = tag.description.get("language", "")
        return TagOut(value=tag.value, text=text, description=description)

    def contains(
        self, tags: [List[Tag]], check_tags: List[TagData]
    ) -> Tuple[List[TagData], List[TagData], Dict[str, Tag]]:
        """
        @param tags:
        @param check_tags:
        @return: a tuple of included, missing and dict: included(value) -> Tag
        """
        contained: List[TagData] = []
        missing: List[TagData] = []
        contained_dict: Dict[str, Tag] = {}
        tags_value_dict = {t.value: t for t in tags}
        tags_values = list(tags_value_dict.keys())
        for check_t in check_tags:
            if check_t.value in tags_values:
                contained.append(check_t)
                contained_dict[check_t.value] = tags_value_dict[check_t.value]
            else:
                missing.append(check_t)
        return contained, missing, contained_dict

    def overlap(
        self, tags: [List[Tag]], check_tags: List[TagData]
    ) -> Tuple[List[TagData], List[Tag], List[Tuple[Tag, TagData]]]:
        """
        @param tags:
        @param check_tags:
        @return: (TagData: missing in db, from db missing in list, match)
        """
        missing_in_db: List[TagData] = []
        match_: List[Tuple[Tag, TagData]] = []
        missing_in_list: List[Tag] = tags[:]

        tags_value_dict = {t.value: t for t in tags}
        tags_values = list(tags_value_dict.keys())
        for check_t in check_tags:
            if check_t.value in tags_values:
                tag: Tag = tags_value_dict[check_t.value]
                match_.append((tag, check_t))
                missing_in_list.remove(tag)
            else:
                missing_in_db.append(check_t)
        return missing_in_db, missing_in_list, match_

    def resolve_from_entry(self, entry: TemplateMerge) -> List[TagData]:
        logger.debug(
            f"resolve_from_entry: {type(entry)}, {entry.slug}, {entry.template}"
        )
        try:
            code_schema = entry.rules.code_schema
            tags = entry.rules.tags
            if code_schema == VALUE_LIST and tags.get("from_list"):
                return self.resolve_from_list_code(entry)
            elif code_schema == VALUE_TREE and tags.get("from_tree"):
                return self.resolve_from_tree_code(entry)
            else:
                pass
            #
        except ApplicationException as err:
            raise err
        else:
            return []

    def resolve_from_list_code(self, entry: TemplateMerge) -> List[TagData]:
        return [self.create_tag_data(value) for value in entry.values.list]

    def resolve_from_tree_code(self, entry: TemplateMerge) -> List[TagData]:
        logger.debug(f"resolve_from_tree_code")
        tags_rules = entry.rules.tags
        # assert entry.template.slug == "value_tree"
        if "levels" in tags_rules["from_tree"]:
            tree_schema = entry.values
            all_level_names = [
                level if type(level) == str else level.value
                for level in tree_schema.levels
            ]
            tag_levels = tags_rules["from_tree"]["levels"]
            if not all(
                [
                    type(tag_level) is int or tag_level in all_level_names
                    for tag_level in tag_levels
                ]
            ):
                logger.error(
                    list(
                        filter(
                            type(tag_level) is not int
                            or tag_level not in all_level_names
                            for tag_level in tag_levels
                        )
                    )
                )
                raise ApplicationException(
                    500,
                    "not all specified tag levels are in defined as levels in the tree",
                )
            level_indexes = []
            for level in tag_levels:
                if type(level) is int:
                    level_indexes.append(level)
                elif type(level) is str:
                    # assert level in tree_schema.levels
                    # print(level, "->", all_level_names.index(level))
                    level_indexes.append(all_level_names.index(level) + 1)
            # print("levels:", tags)
            tags = self.recursive_tag_gen(
                tree_schema,
                level_indexes,
                tags_rules["from_tree"].get("remain_hierarchy", False),
            )
            # tags = flatten_sequence(tags)
            return tags
        logger.warning(f"Could not generate tags from entry: {entry.slug}")
        return []

    def recursive_tag_gen(
        self, tree: ValuesMerge, grab_levels: List[int], remain_hierarchy: bool = False
    ) -> List[TagData]:
        """
        recursively creates Tag objects from a tree for all levels specified in grab_levels.
        returns a list of tags.
        """
        results = []

        def rec_grab_at_levels(
            node: ItemMerge, parent: Optional[ItemMerge] = None, act_level: int = 0
        ):
            act_level_tag = None
            if act_level in grab_levels:
                act_level_tag = self.create_tag_data(node, parent, remain_hierarchy)
                results.append(act_level_tag)
            if node.children:
                for child in node.children:
                    rec_grab_at_levels(child, act_level_tag, act_level + 1)

        rec_grab_at_levels(tree.root)
        return results

    def create_tag_data(
        self, node: ItemMerge, parent: ItemMerge = None, remain_hierarchy: bool = False
    ) -> TagData:
        t = TagData(value=node.value, text=node.text, description=node.description)
        if parent and remain_hierarchy:
            t.parent_value = parent.value
        return t

    def create_tag(self, td: TagData, language: str, source_entry: Entry):
        # , source_entry=source_entry

        tag = Tag(
            value=td.value, text={language: td.text}, source_slug=source_entry.slug
        )
        if td.description:
            tag.description = td.description
        return tag

    def update_tag(self, tag: Tag, td: TagData, language):
        tag.text[language] = td.text
        flag_modified(tag, "text")
        if td.description:
            tag.description[language] = td.description
            flag_modified(tag, "description")

    def remove_tag(self, tag: Tag, language: str):
        # todo try flag_modified
        # n_text = tag.text
        del tag.text[language]
        # tag.text = n_text
        flag_modified(tag, "text")
        if language in tag.description:
            del tag.description[language]
            flag_modified(tag, "description")
        if len(tag.text) == 0:
            self.db_session.delete(tag)

    def get_tags_from_entry_tags(
        self, entry: Entry, entry_tags: Dict[str, str]
    ) -> List[Tag]:
        """
        @param entry:
        @param entry_tags:
        @return:
        """
        res: List[Tuple[str, str]] = []  # tag-value, source_slug (code-e)
        for (tag, group) in entry_tags.items():
            t = None
            # ref.reference.tag can be a dict or a list
            for ref in entry.template.entry_refs:
                tag_ref = ref.reference.get("tag", None)
                if tag_ref:
                    if isinstance(tag_ref, list):
                        for i_tag_ref in tag_ref:
                            if i_tag_ref["name"] == group:
                                t = ref
                                break
                    else:
                        if tag_ref["name"] == group:
                            t = ref
            if t:
                res.append((tag, t.reference["dest_slug"]))
            else:
                logger.warning(f"Entry tag cannot be resolved: {tag}/{group}")
                # if ref.reference.get("tag", None):
                #     logger.warning(f"Tag ref: {tag_ref}. tag_ref names: {[tr['name'] for tr in tag_ref]}. looking for group: {group}")
                # else:
                #     logger.warning(f"No tag-ref to match '{group}' {entry.template.entry_refs}")

        clause = or_(
            *[and_(Tag.value == tt[0], Tag.source_slug == tt[1]) for tt in res]
        )
        tags: List[Tag] = self.db_session.query(Tag).filter(clause).all()

        if len(entry_tags) != len(tags):
            logger.warning("Not all tags could be found")
            logger.warning(
                f"tags on the entry {len(entry_tags)} ,tags given: {len(tags)}"
            )
        return tags

    def delete_tags(self, entry: Entry):
        if entry.type == CODE:
            self.delete_for_slug_lang(entry.slug, entry.language)

    def delete_for_slug_lang(self, slug: str, language_code: str):
        tags: List[Tag] = self.get_from_slug(slug)
        for tag in tags:
            self.remove_tag(tag, language_code)
