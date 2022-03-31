from logging import getLogger
from typing import Dict, Any, Type, Union

from fastapi.encoders import jsonable_encoder
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

from app.models.orm import Entry

logger = getLogger(__name__)


class ApplicationException(Exception):
    def __init__(
        self,
        status_code: int,
        msg: Union[str, Exception] = "",
        data: Dict[str, Any] = None,
    ):
        self.name = "ApplicationException"
        self.msg = str(msg)
        self.data = data
        self.status_code = status_code


async def application_exception_handler(request: Request, exc: ApplicationException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "msg": exc.msg,
            "data": jsonable_encoder(exc.data),
            "error": {"msg": exc.msg},
        },
    )


async def exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unknown exception for {request.url}: !!")
    logger.exception(exc)
    # err = create_error_response(code=exc.status_code, msg=exc.msg, data=exc.data)
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR, content=dict(exception=str(exc))
    )  # status_code=exc.status_code, content=err.dict(exclude_unset=True))


def raise_exists_already(obj_type: Type):
    msg = "Exists already"
    if obj_type == Entry:
        msg = "Entry exists already"
    raise ApplicationException(HTTP_400_BAD_REQUEST, msg)
