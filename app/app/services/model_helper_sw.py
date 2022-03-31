from logging import getLogger
from typing import Set, Tuple, Dict, Union, Any

from pydantic.main import BaseModel

from app.models.orm import Base
from app.services.service_worker import ServiceWorker

logger = getLogger(__name__)


class ModelHelperService:
    def __init__(self, root_sw: ServiceWorker):
        self.root_sw = root_sw
        self.db_session = root_sw.db_session

    # noinspection PyDefaultArgument
    def update_model(
        self,
        existing_model: Union[BaseModel, Base],
        new_model: BaseModel,
        auto_update: bool = True,
        prevent_auto_update: Set = {},
    ):
        changes: Dict[str, Tuple] = {}

        for field in new_model.__fields__.keys():
            if (ev := getattr(existing_model, field, None)) != (
                nv := getattr(new_model, field, None)
            ):
                logger.debug(f"field change: {field}")
                logger.debug(
                    f"{getattr(existing_model, field, None)} ==> {getattr(new_model, field, None)}"
                )
                changes[field] = (ev, nv)
                if auto_update:
                    try:
                        if field in prevent_auto_update:
                            continue
                        else:
                            setattr(existing_model, field, nv)
                    except:
                        # logger.error(err)
                        logger.error(f"Could not update field: {field}")
                        pass

    # noinspection PyDefaultArgument
    def update_obj_from_model(
        self,
        existing_obj: Base,
        new_model: BaseModel,
        ignore: set = {},
        replace: Dict[str, Any] = {},
    ) -> Dict[str, Tuple[Any, Any]]:
        changes = {}
        for field in filter(lambda f: f not in ignore, new_model.__fields__.keys()):
            # check if changed
            # beware of foreign-key stuff
            n_val = replace[field] if field in replace else getattr(new_model, field)
            logger.debug(
                f"checking field: {field}, {n_val} (old): {getattr(existing_obj, field, None)}"
            )
            if isinstance(n_val, BaseModel):
                n_val = n_val.dict(exclude_none=True)
            if (e_val := getattr(existing_obj, field, None)) != n_val:
                logger.debug(f"field change: {field}")
                logger.debug(f"{e_val} ==> {n_val}")
                changes[field] = (e_val, n_val)
                setattr(existing_obj, field, n_val)
        return changes

    def get_as_dict(self, obj, fields):
        return {f: getattr(obj, f) for f in fields}
