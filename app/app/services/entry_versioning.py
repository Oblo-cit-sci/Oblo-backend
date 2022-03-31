"""
getting template/code entries of specific versions and creating version updates
"""
import time
from logging import getLogger
from typing import Union, List

from deepdiff import Delta, DeepDiff
from deprecated.classic import deprecated
from sqlalchemy.orm import Query
from sqlalchemy.orm.attributes import flag_modified
from starlette.status import HTTP_404_NOT_FOUND

from app.models.orm import Entry
from app.models.schema import TemplateBaseInit, TemplateMerge, EntryMainModel
from app.models.schema.entry_schemas import EntryDeltaModel
from app.services.entry_sw import EntryInModels
from app.services.entry import entry_descriptor
from app.util.consts import SCHEMA, VERSION, BASE_ENTRIES, CONCRETE_ENTRIES, CODE, REGULAR, BASE_SCHEMA_ENTRIES
from app.util.exceptions import ApplicationException

logger = getLogger(__name__)


class EntryVersioningService:
    """
    getting template/code entries of specific versions and creating version updates
    """

    def __init__(self, templace_code_service):
        from app.services.template_code_entry_sw import TemplateCodeService
        self.parent_sw: TemplateCodeService = templace_code_service
        self.db_session = self.parent_sw.root_sw.db_session

    # noinspection PyMethodMayBeStatic
    def get_version(self, entry: Union[TemplateBaseInit, TemplateMerge], version: int) -> EntryMainModel:
        """
        get a specific version of an entry (for templates and codes)...
        todo should later be in entry_sw also giving version of regulars
        @param entry: original entry
        @param version: version number
        @return: versioned entry
        """
        if not (0 < version <= entry.version):
            raise ApplicationException(
                HTTP_404_NOT_FOUND,
                "Invalid version number",
                data={"given": version, "min": 1, "max": entry.version},
            )
        apply_diffs_from_end = entry.version - version
        # todo later work with MainModel instead of db_entry?
        result = entry.dict(exclude_none=True)
        # logger.warning(
        #     f"{entry.version}, {version}, {apply_diffs_from_end}"
        # )
        for index in range(apply_diffs_from_end):
            version_change = Delta(entry.get_db_entry().changes[(-1 - index)])
            result += version_change
        result[VERSION] = version
        return type(entry).parse_obj(result)

    # noinspection PyMethodMayBeStatic
    def update_version(self, entry: Entry, new_entry_model: EntryInModels):
        """
        only perform a version update if there are regular entry depending on this template.
        For a base entry all regulars of all languages need to be checked.
        For concrete templates (with language) only those need to be checked.
        """

        new_entry_model.version = entry.version
        if entry.type in BASE_SCHEMA_ENTRIES:
            version_update = True
        else:
            concretes_ids = [c.id for c in [entry]]
            version_update = self.get_query_regulars_of_concretes(concretes_ids, entry.version).first() is not None
        has_dependent_regulars = self._check_has_depending_regulars(entry)
        if version_update:
            # if is a bit redundant, should be called for regular entries...
            # or shouldn't matter...

            delta = self.code_template_delta(entry, new_entry_model)
            if not entry.changes:
                entry.changes = [delta]
            else:
                entry.changes.append(delta)
            flag_modified(entry, "changes")
            # logger.warning(f"...length of changes-list {len(entry.changes)}")
            entry.version += 1
        else:
            # logger.info(f"No dependencies... updating last changes...")
            self.smash_version_changes(entry)
        logger.info(f"updated {entry_descriptor(entry)}")
        return entry.version

    @deprecated
    def _check_has_depending_regulars(self, entry: Entry) -> bool:
        """
        check if there are regular entries depending on this template.
        """
        if entry.type == SCHEMA:
            # todo use function. use persist_sw
            p = self.parent_sw.persist
            base_entries = p.base_q().p.type_filter([CODE]).filter(Entry.template_id == entry.id).all()
            concretes = []
            for base_entry in base_entries:
                concretes.extend(self.parent_sw.get_all_concretes(base_entry.slug))
            logger.warning("Schema update!")
        if entry.type in BASE_ENTRIES:
            concretes = self.parent_sw.get_all_concretes(entry.slug)
        elif entry.type in CONCRETE_ENTRIES:
            concretes = [entry]
        else:
            logger.error(f"update-version on {entry.type} has no effect")
            return False
        # todo : better use a function, but should ignore privacy
        concretes_ids = [c.id for c in concretes]
        # noinspection PyUnresolvedReferences
        return self.get_query_regulars_of_concretes(concretes_ids, entry.version).first() is not None

    def get_query_regulars_of_concretes(self, concrete_ids: List[int], version: int) -> Query:
        """
        get all regular entries of concrete entries
        """
        # noinspection PyUnresolvedReferences
        return self.parent_sw.persist.base_q(types=[REGULAR]).filter(Entry.template_id.in_(concrete_ids),
                                                                     Entry.template_version == version)

    def code_template_delta(
            self, entry: Union[Entry, EntryInModels], entry_model: EntryInModels
    ):
        if isinstance(entry, Entry):
            conv_entry = self.parent_sw.to_proper_model(entry)
        else:
            conv_entry = entry
        prev_data = EntryDeltaModel.parse_obj(conv_entry.dict(exclude_none=True)).dict(exclude_none=True)
        new_data = EntryDeltaModel.parse_obj(entry_model.dict(exclude_none=True))
        new_data.timestamp = int(time.time())
        new_data = new_data.dict(exclude_none=True)
        # logger.warning(prev_data)
        # logger.warning(new_data)
        delta = Delta(DeepDiff(new_data, prev_data))
        # logger.warning(delta)
        return delta.dumps()

    def check_can_smash_version_changes(self, base_entry: Entry):
        """
        check if all concrete entries use the same base-entry version and have no regular depending on it.
        In that case, we can smash the latest version
        @param base_entry: base entry
        @return: True if version is ok
        """
        concretes = self.parent_sw.get_all_concretes(base_entry.slug)
        base_entry_version = base_entry.version
        if base_entry_version > 1:
            if all(concrete.template_version == base_entry_version for concrete in concretes):
                self.smash_version(base_entry)
                # logger.warning(f"TEST: smash version: {base_entry.slug}")
                # base_model = TemplateBaseInit.from_orm(base_entry)
                # logger.warning(base_model.dict(exclude_none=True))
                # logger.warning(self.get_version(base_model, base_entry_version - 1).dict(exclude_none=True))
            else:
                logger.warning(f"TEST: no smash version: {base_entry.slug}")

    def smash_version(self, entry: Entry):
        """
        smash the latest version of the template
        @param entry: template entry
        @return: new version
        """
        logger.debug(f"smash version: {entry.slug}")
        self.smash_version_changes(entry)
        entry.version -= 1
        self.parent_sw.persist.base_q().filter(Entry.template_id == entry.id).update(
            {Entry.template_version: entry.version})

    def smash_version_changes(self, entry: Entry):
        current_model = self.parent_sw.to_proper_model(entry)
        last_version = self.get_version(self.parent_sw.to_proper_model(entry), max(1, (entry.version - 1)))
        delta = self.code_template_delta(last_version, current_model)
        if last_version.version > 1:
            if not entry.changes:
                entry.changes = [delta]
            else:
                entry.changes[len(entry.changes) - 1] = delta
            flag_modified(entry, "changes")
        logger.warning(f"TEST: smash version: {entry.slug}, {entry.version}")
