from logging import getLogger
from typing import Optional

from fastapi import APIRouter, Body, Depends
from pydantic import UUID4
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_404_NOT_FOUND,
)

from app.dependencies import get_current_actor, get_sw
from app.models.examples import entry_in_ex
from app.models.orm import RegisteredActor
from app.models.orm.entry_orm import Entry
from app.models.schema import EntryMeta, MapEntry
from app.models.schema.entry_schemas import EntryOut, EntryApiUpdateIn, EntryRegular
from app.models.schema.response import (
    GenResponse,
    simple_message_response,
)
from app.services.entry import (
    delete_entry_folder,
)
from app.services.service_worker import ServiceWorker
from app.services.util.entries2geojson import entry2features_no_multipoint
from app.util.consts import PUBLISHED, REJECTED, REGULAR, SLUG, ENTRY
from app.util.exceptions import raise_exists_already, ApplicationException

router = APIRouter(prefix="/entry", tags=["Entry"])


logger = getLogger(__name__)


@router.post("/{uuid}", status_code=HTTP_201_CREATED, responses={400: {}})
async def create(
    request: Request,
    entry_in: EntryRegular = Body(..., example=entry_in_ex),
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    # logger.warning(entry_in.dict())
    if sw.entry.exists(entry_in.uuid):
        raise raise_exists_already(Entry)

    # todo needs to be higher up..
    if current_actor:
        sw.actor.get_visitor()
    entry = sw.entry.process_entry_post(entry_in, current_actor)
    request.state.current_entry = entry
    # is also put to request.state.current_actor
    sw.entry.post_create(current_actor, request.state.current_entry)
    if not current_actor:
        request.session.setdefault("created_entries", []).append(str(entry.uuid))
    entry_out = EntryOut.from_orm(entry)
    if entry.template:
        entry_out.template = {SLUG: entry.template.slug}

    # todo this is not the proper id, but the backend is gonna fix it
    map_feature = entry2features_no_multipoint(MapEntry.from_orm(entry))
    return GenResponse(
        data={ENTRY: entry_out, "map_features": map_feature},
        msg=sw.t("entry.submitted"),
    )


@router.get("/{uuid}")
async def get(
    uuid: UUID4,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    db_obj: Entry = sw.entry.crud_get(uuid)
    db_obj.has_read_access(current_actor, True)

    # wtf
    if db_obj.type == REGULAR:
        em = sw.entry.create_entry_gen(db_obj, current_actor, EntryOut)
        sw.entry.regular_out_add_protected_info(em, db_obj, current_actor)
    else:
        em = EntryOut.from_orm(db_obj)
    if not em:
        raise ApplicationException(
            HTTP_404_NOT_FOUND, msg=sw.t("entry.could_not_fetch")
        )
        # return sw.error_response(HTTP_404_NOT_FOUND, msg="entry.could_not_fetch")
    # map_feature = entry2features_no_multipoint(em)
    # return GenResponse(data={"entry": em, "map_features": map_feature}, msg=sw.t("entry.updated"))
    return GenResponse(data=em)


@router.get(
    "/{uuid}/meta",
    response_model=GenResponse[EntryMeta],
    response_model_exclude_none=True,
)
async def get_meta(
    uuid: UUID4,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    db_obj: Entry = sw.entry.crud_get(uuid)
    db_obj.has_read_access(current_actor, True)
    em = sw.entry.create_entry_gen(db_obj, current_actor, EntryMeta)
    return GenResponse(data=em)


@router.get(
    "/{uuid}/exists", response_model=GenResponse, response_model_exclude_none=True
)
async def exists(
    uuid: UUID4,
    sw: ServiceWorker = Depends(get_sw),
):
    existing: Optional[Entry] = sw.entry.crud_get(uuid, False)
    if existing:
        logger.warning("There is an entry draft that already exists")
    return GenResponse(data=True if existing else False)


@router.patch("/{uuid}", status_code=HTTP_200_OK)
async def update(
    uuid: UUID4,
    entry_in: EntryApiUpdateIn,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    db_obj: Entry = sw.entry.crud_get(uuid)
    sw.entry.check_has_write_access(db_obj, current_actor)
    entry = sw.entry.update(db_obj, entry_in)
    entry_out = EntryOut.from_orm(entry)
    if entry.template:
        entry_out.template = {SLUG: entry.template.slug}
    # todo this is not the proper id, but the backend is gonna fix it
    map_feature = entry2features_no_multipoint(MapEntry.from_orm(entry))
    return GenResponse(
        data={ENTRY: entry_out, "map_features": map_feature},
        msg=sw.t("entry.updated"),
    )


@router.patch("/{uuid}/accept", status_code=HTTP_200_OK)
async def accept(
    uuid: UUID4,
    entry_in: EntryApiUpdateIn,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    db_obj: Entry = sw.entry.crud_get(uuid)
    sw.entry.check_has_write_access(db_obj, current_actor)
    entry = sw.entry.process_review(db_obj, entry_in, current_actor, PUBLISHED)
    entry_out = EntryOut.from_orm(entry)
    if entry.template:
        entry_out.template = {SLUG: entry.template.slug}
    map_feature = entry2features_no_multipoint(MapEntry.from_orm(entry))
    return GenResponse(
        data={ENTRY: entry_out, "map_features": map_feature},
        msg=sw.t("entry.review_accepted"),
    )


@router.patch("/{uuid}/reject", status_code=HTTP_200_OK)
async def reject(
    uuid: UUID4,
    entry_in: EntryApiUpdateIn,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    db_obj: Entry = sw.entry.crud_get(uuid)
    sw.entry.check_has_write_access(db_obj, current_actor)
    entry_out = sw.entry.process_review(db_obj, entry_in, current_actor, REJECTED)
    return GenResponse(data=entry_out, msg=sw.t("entry.review_rejected"))


@router.delete("/{uuid}")
async def delete(
    uuid: UUID4,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    db_obj: Entry = sw.entry.crud_get(uuid)
    sw.entry.check_has_write_access(db_obj, current_actor)
    sw.tag.delete_tags(db_obj)
    try:
        sw.db_session.delete(db_obj)
        sw.db_session.commit()
        delete_entry_folder(uuid)
    except:
        return sw.error_response(
            HTTP_500_INTERNAL_SERVER_ERROR, msg="entry.delete_fail"
        )

    return sw.msg_response("entry.delete_ok")


@router.post("/{uuid}/share")
async def share(
    uuid: UUID4,
    password: Optional[str] = None,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    entry: Entry = sw.entry.crud_get(uuid)
    entry.is_creator(current_actor)
    link = sw.entry.create_share_link(entry)
    return GenResponse(
        data={"url": link}, msg="EN:share link created"
    )  # Response(csv,media_type="text/csv")


@router.get("/{uuid}/get_shared/{access_key}")
async def get_shared(
    uuid: UUID4,
    access_key: UUID4,
    password: Optional[str] = None,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    entry: Entry = sw.entry.crud_get(uuid)
    sw.entry.share_access_key_is_valid(entry, access_key, password)
    if entry.type == REGULAR:
        em = sw.entry.create_entry_gen(entry, current_actor, EntryOut)
    else:
        em = EntryOut.from_orm(entry)
    return GenResponse(data=em)


@router.post("/{uuid}/revoke_share")
async def share(
    uuid: UUID4,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    entry: Entry = sw.entry.crud_get(uuid)
    entry.is_creator(current_actor)
    if sw.entry.revoke_share_link(entry):
        return simple_message_response(
            msg="EN:share link revoked"
        )
    else:
        return simple_message_response(msg="EN:there was no sharelink")


@router.post("/{uuid}/version_update")
async def version_update(
        uuid: UUID4,
        sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor)
):
    pass