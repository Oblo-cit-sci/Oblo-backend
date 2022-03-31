from logging import getLogger
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import UUID4
from sqlalchemy.orm.exc import NoResultFound
from starlette.requests import Request
from starlette.responses import Response, FileResponse, JSONResponse
from starlette.status import HTTP_404_NOT_FOUND

from app.dependencies import get_current_actor, get_sw
from app.models.orm import RegisteredActor, Entry
from app.models.schema.response import ErrorResponse, GenResponse
from app.services.entry import (
    get_file_path,
    delete_entry_attachment,
    save_for_entry,
    get_attachment_path,
)
from app.services.service_worker import ServiceWorker

entry_uuid_attachment_router = APIRouter(
    prefix="/entry/{uuid}/attachment", tags=["Entry/File"]
)
entry_slug_attachment_router = APIRouter(
    prefix="/entry/{slug}/entry_file", tags=["Entry/File"]
)

logger = getLogger(__name__)


@entry_slug_attachment_router.get("/{file_name}")
async def entry_slug_get_file(
    slug: str,
    file_name: str,
    response: Response,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
) -> Union[FileResponse, JSONResponse]:
    try:
        sw.template_codes.get_base_schema_by_slug(slug).has_read_access(current_actor)
        attachment_path = get_file_path(slug, file_name)

        if attachment_path:
            return FileResponse(attachment_path)
        else:
            response.status_code = HTTP_404_NOT_FOUND
            return sw.error_response(HTTP_404_NOT_FOUND, "Entry not found")

    except NoResultFound:
        response.status_code = HTTP_404_NOT_FOUND
        return sw.error_response(HTTP_404_NOT_FOUND, "Entry not found")
    except HTTPException as err:
        response.status_code = err.status_code
        return sw.error_response(HTTP_404_NOT_FOUND, "File not found")


@entry_uuid_attachment_router.post("/{file_uuid}")
async def create_attachment(
    uuid: UUID4,
    file_uuid: UUID4,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
):
    try:
        sw.entry.check_has_write_access(sw.entry.crud_get(uuid), current_actor)
        save_for_entry(uuid, file_uuid, file)
        return sw.msg_response("entry.file_upload")
    except NoResultFound:
        response.status_code = HTTP_404_NOT_FOUND
        return sw.error_response(HTTP_404_NOT_FOUND, "Entry not found")
    except HTTPException as err:
        response.status_code = err.status_code
        return sw.error_response(HTTP_404_NOT_FOUND, "File not found")


@entry_uuid_attachment_router.get(
    "/{file_uuid}",
    responses={HTTP_404_NOT_FOUND: {"File not found": None}},
    response_model_exclude_none=True,
)
async def get_attachment(
    uuid: UUID4,
    file_uuid: UUID4,
    response: Response,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
) -> Union[FileResponse, JSONResponse]:
    try:
        sw.entry.crud_get(uuid).has_read_access(current_actor)
        attachment_path = get_attachment_path(uuid, file_uuid)
        if attachment_path:
            return FileResponse(attachment_path)
        else:
            response.status_code = HTTP_404_NOT_FOUND
            return sw.error_response(
                HTTP_404_NOT_FOUND, "File not found"
            )  # todo translate

    except NoResultFound:
        response.status_code = HTTP_404_NOT_FOUND
        return sw.error_response(HTTP_404_NOT_FOUND, "Entry not found")
    except HTTPException as err:
        response.status_code = err.status_code
        return sw.error_response(HTTP_404_NOT_FOUND, "File not found")


@entry_uuid_attachment_router.delete("/{file_uuid}")
async def delete_attachment(
    uuid: UUID4,
    file_uuid: UUID4,
    response: Response,
    sw: ServiceWorker = Depends(get_sw),
    current_actor: RegisteredActor = Depends(get_current_actor),
) -> JSONResponse:
    try:
        db_obj: Entry = sw.entry.check_has_write_access(
            sw.entry.crud_get(uuid), current_actor
        )

        if db_obj.image == str(file_uuid):
            logger.debug("unsetting entry image")
            db_obj.image = None

        db_obj.attached_files = filter(
            lambda attachment: attachment["file_uuid"] != str(file_uuid),
            db_obj.attached_files,
        )
        sw.db_session.add(db_obj)
        sw.db_session.commit()

        success = delete_entry_attachment(uuid, file_uuid)

        if success:
            return sw.msg_response("entry.image_delete_ok")
        else:
            return sw.error_response(HTTP_404_NOT_FOUND, "entry.image_delete_fail")
    except NoResultFound:
        response.status_code = HTTP_404_NOT_FOUND
        return sw.error_response(HTTP_404_NOT_FOUND, "Entry not found")
    except HTTPException as err:
        response.status_code = err.status_code
        return sw.error_response(HTTP_404_NOT_FOUND, "File not found")
