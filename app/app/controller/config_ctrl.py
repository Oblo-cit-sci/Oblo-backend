from logging import getLogger
from typing import List, Any, Optional

from fastapi import APIRouter, Depends
from pydantic.error_wrappers import ValidationError
from sqlalchemy.orm import Session
from starlette.status import HTTP_200_OK

from app.dependencies import get_db, is_admin, get_sw
from app.models.orm.entry_orm import Entry
from app.services.service_worker import ServiceWorker
from app.settings import env_settings, Settings
from app.util.consts import REGULAR, BASE_CODE, BASE_TEMPLATE, CODE, TEMPLATE, SCHEMA
from app.util.exceptions import ApplicationException

router = APIRouter(prefix="/config", tags=["Config"])

logger = getLogger(__name__)


@router.post("/flip_echo", include_in_schema=False)
async def flip_echo(db_session: Session = Depends(get_db), _=Depends(is_admin)):
    new_val = False if db_session.bind.echo else True
    db_session.bind.echo = new_val
    return {"echo": new_val}


# @router.post("/create_tags", include_in_schema=False)
# async def route_create_tags(
#         title: str,
#         db_session: Session = Depends(get_db),
#         user: RegisteredActor = Depends(login_required),
#         admin=Depends(is_admin),
# ):
#     entry = db_session.query(Entry).filter(Entry.title == title).first()
#     entry_schema = EntryOut.from_orm(entry)
#     return tag.create_tags(entry, db_session)


@router.post("/routes", include_in_schema=False)
async def all_routes():
    from main import app

    # print(app.routes)
    from fastapi.routing import APIRoute
    from starlette.routing import Mount

    for route in app.routes:

        if route.__class__ is APIRoute:
            route: APIRoute = route
            print("%s: (%s): %s" % (route.__class__.__name__, route.path, route.name))
        elif route.__class__ is Mount:
            route: Mount = route
            print("%s: (%s): %s" % (route.__class__.__name__, route.path, route.name))
            print(route.routes)
        else:
            print(route.__class__)
    return 10


@router.get("/clear_regular", dependencies=[Depends(is_admin)], include_in_schema=env_settings().ENV == "dev")
def clear_regular(slug: Optional[str] = None, language: Optional[str] = None, sw: ServiceWorker = Depends(get_sw)):
    query = sw.entry.db_session.query(Entry).filter(Entry.type == REGULAR)

    if slug:
        template_ids = [e.id for e in sw.template_codes.get_all_concretes(slug)]
        query = sw.entry.db_session.query(Entry).filter(Entry.type == REGULAR, Entry.template_id.in_(template_ids))
    if language:
        query = query.filter(Entry.language == language)
    entries: List[Entry] = query.all()
    for e in entries:
        sw.db_session.delete(e)
    sw.db_session.commit()
    return {"num_entries": len(entries)}


@router.get(
    "/clear_all_entries", dependencies=[Depends(is_admin)], include_in_schema=False
)
def clear_all_entries(sw: ServiceWorker = Depends(get_sw)):
    entries: List[Entry] = sw.entry.db_session.query(Entry).all()
    for e in entries:
        sw.db_session.delete(e)
    sw.db_session.commit()
    return len(entries)


@router.get("/check_server")
def check_server():
    return "ok"


@router.get(
    "/get_installed_packages", dependencies=[Depends(is_admin)], status_code=HTTP_200_OK
)
def get_installed_packages():
    import pkg_resources

    installed_packages = pkg_resources.working_set
    installed_packages_list = sorted([(i.key, i.version) for i in installed_packages])
    return installed_packages_list


@router.get("/env_setting")
async def change_env_setting(
        var_name: str, _=Depends(is_admin), sw: ServiceWorker = Depends(get_sw)
):
    if not hasattr(env_settings(), var_name):
        raise ApplicationException(
            422, f"The environmental variable of the name {var_name} does not exists"
        )
    return sw.data_response({var_name: getattr(env_settings(), var_name)})


@router.get("/change_env_setting")
async def change_env_setting(var_name: str, var_new_value: Any, _=Depends(is_admin)):
    settings = env_settings()
    if not hasattr(settings, var_name):
        raise ApplicationException(422, "EN: Unknown variable")
    prev_value = getattr(settings, var_name)
    try:
        field_type = Settings.__fields__[var_name].outer_type_
        if field_type == int:
            casted_type = int(var_new_value)
        elif field_type == bool:
            casted_type = var_new_value == "True"
        else:
            raise ApplicationException(
                500, f"variable should be casted to... {field_type}. Aborting..."
            )
        new_settings = Settings.parse_obj(
            {**env_settings().dict(), **{var_name: casted_type}}
        )
        setattr(env_settings(), var_name, casted_type)
    except ValidationError as err:
        logger.error(err)
        raise ApplicationException(422)
    # validation = Settings.__fields__[var_name].validate(var_new_value,{}, loc="")
    # if type(validation[1]) == ErrorWrapper:
    #     raise ApplicationException(422, validation[1].exc.message_template)
    # setattr(settings, var_name, var_new_value)
    return {"prev_value": prev_value, "new_value": getattr(new_settings, var_name)}


@router.get("/migrate")
def migrate(
        version_reset: bool = False,
        regulars_reset: bool = False,
        sw: ServiceWorker = Depends(get_sw),
):
    # KILL SCHEMA DUPLICATES
    schemas = sw.db_session.query(Entry).filter(Entry.type == SCHEMA).all()
    min_id = {}

    schema_slug_entries_dict = {}
    for e in schemas:
        min_id[e.slug] = min(min_id.get(e.slug, e.id), e.id)
        schema_slug_entries_dict.setdefault(e.slug, []).append(e)

    for entries in schema_slug_entries_dict.values():
        logger.warning(f"Deleting duplicates: {len(entries) - 1}")
        for e in entries:
            if e.id != min_id[e.slug]:
                logger.warning("Deleting duplicate: %s" % e.id)
                sw.db_session.delete(e)
    sw.db_session.commit()
    # DONE

    entries = sw.db_session.query(Entry).filter(Entry.type != REGULAR).all()
    entry_dicts = [
        {
            "slug": e.slug,
            "type": e.type,
            "language": e.language,
            "version": e.version,
            "template_version": e.template_version,
            "template": {
                "slug": e.template.slug,
                "type": e.template.type,
                "version": e.template.version,
            }
            if e.template
            else None,
        }
        for e in entries
    ]

    if version_reset:
        for e in entries:
            if e.type in [BASE_CODE, BASE_TEMPLATE, CODE, TEMPLATE]:
                e.version = 1
                if e.type in [BASE_CODE, CODE, TEMPLATE]:
                    e.template_version = 1
            e.changes = []
        sw.db_session.commit()

    if regulars_reset:
        regulars = sw.db_session.query(Entry).filter(Entry.type == REGULAR).all()
        article_review_en = sw.template_codes.get_by_slug_lang("article_review", "en")
        logger.warning(len(regulars))
        for reg in regulars:
            # logger.warning(f"{reg.template.slug}, {reg.template.type}")
            reg.template_version = 1
            if reg.template.slug == "article_review":
                reg.template = article_review_en
            else:
                sw.db_session.delete(reg)
        sw.db_session.commit()

    return entry_dicts, {
        slug: len(entries) for (slug, entries) in schema_slug_entries_dict.items()
    }


@router.get("/migrate_entry_changes")
def migrate_entry_changes(sw: ServiceWorker = Depends(get_sw)):
    entries = sw.db_session.query(Entry).all()
    for entry in entries:
        entry.changes = []
    sw.db_session.commit()

# @router.get("/migrate_entry_lang")
# def migrate(db_session: Session = Depends(get_db), admin=Depends(is_admin)):
#     entries = db_session.query(Entry).all()
#     for e in entries:
#         e.language = "en"
#     db_session.commit()
#     return len(entries)


# @router.post("/fix_tags", include_in_schema=False)
# async def fix_tags(
#         db_session: Session = Depends(get_db),
#         user: RegisteredActor = Depends(login_required),
#         admin=Depends(is_admin),
# ):
#     all_tags = db_session.query(Tag).all()
#     # print(all_tags)
#     unique_title = set([t.title for t in all_tags])
#     for title in unique_title:
#         matching_tags = list(filter(lambda t: t.title == title, all_tags))
#         different_sources = list(set(t.source_entry_id for t in matching_tags))
#         if len(matching_tags) > 1:
#             if len(different_sources) > 1:
#                 print(title, "more then 1 source")
#                 continue
#             else:
#                 for t in matching_tags[1:]:
#                     db_session.delete(t)
#     # print(title, len(matching_tags))
#     db_session.commit()
#     return [TagData.from_orm(t) for t in all_tags]


# @router.get("/migrate_fix_observer")
# def migrate(db_session: Session = Depends(get_db), admin=Depends(is_admin)):
#     # v 0.10.11
#     entries = db_session.query(Entry).filter(Entry.template_id.in_([18, 19, 369])).all()
#     change = {}
#     que = {}
#     fix = {}
#     for e in entries:
#         # res[e.uuid] = e.values["Observer"]
#         val = e.values["Observer"]["value"]
#         if isinstance(val, list):
#             if len(val) == 1:
#                 if val[0] in ["somebody else", "only me"]:
#                     change[e.uuid] = (e.values["Observer"], {"value": val[0]})
#                     # if str(e.uuid) == "3affa8cf-bb35-41e1-85cc-5e9129a30427":
#                     #     fix[e.uuid] = "ok"
#                     e.values["Observer"] = {"value": val[0]}
#                     from sqlalchemy.orm.attributes import flag_modified
#                     flag_modified(e, "values")
#                     db_session.commit()
#                     continue
#                 if val[0] == "me":
#                     change[e.uuid] = (e.values["Observer"], {"value": "only me"})
#                     continue
#         que[e.uuid] = val
#     return {"total": len(entries), "change": change, "que": que, "fix": fix}


# @router.get("/find_ar_with_adaptations")
# async def find_ar_with_adaptations(sw: ServiceWorker = Depends(get_sw), admin=Depends(is_admin)):
#     # v 0.10.11
#     entries = sw.db_session.query(Entry).filter(Entry.template_id.in_([15])).all()  # 14
#     has_ada = {}
#
#     logger.warning(len(entries))
#     for index, e in enumerate(entries):
#         logger.warning(index)
#         ada = e.values.get("adaptations", {}).get("value", None)
#         if ada:
#             em = sw.entry.create_entry_gen(e, admin, EntryOut).dict()
#             has_ada[e.uuid] = {"title": e.title, "ada": ada, "tags": em["tags"], "IPLC name": e.values["IPLC name"]}
#     logger.warning("done")
#     return has_ada
