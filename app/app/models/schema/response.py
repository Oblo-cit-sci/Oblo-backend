from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel
from pydantic.generics import GenericModel
from starlette.responses import JSONResponse

from app.util.files import orjson_dumps

GenResponseType = TypeVar("GenResponseType")


class Error(BaseModel):
    code: int
    msg: str
    data: Dict[str, Any] = None


class GenResponse(GenericModel, Generic[GenResponseType]):
    data: Optional[GenResponseType]
    msg: Optional[str] = ""
    error: Optional[Error]  # deprecated

    class Config:
        json_dumps = orjson_dumps


simple_message_response = GenResponse
ErrorResponse = GenResponse[str]  # todo just use ErrorResponse
NewErrorResponse = GenResponse


def create_error_response(
    code: int = 400, msg: str = "", data: Dict[str, Any] = None
) -> JSONResponse:
    return JSONResponse(
        status_code=code, content={"code": code, "msg": msg, "data": data}
    )
