import re
from datetime import date
from typing import Dict, List, Optional, Union
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, validator, SecretStr
from pydantic.schema import datetime
from starlette.status import HTTP_400_BAD_REQUEST

import app
from app.models.schema import ActorBase, ActorEntryRelationOut, InConfig

""" TODO
all these applicationexc should not be here. However we need something
maybe take application-exception to models-schemas, AND return {MESSAGE_TABLE_INDEX_COLUMN} and 
set the right response words (language) in the handler

"""


class ActorSearchOut(ActorBase):
    description: str = ""
    global_role: Optional[str] = None
    account_deactivated: Optional[bool] = None


class EntriesMetaPaginated(BaseModel):
    entries: List[ActorEntryRelationOut]
    count: int
    prev: Optional[int]
    next: Optional[int]


class ActorSimpleOut(ActorBase):
    """
    for other actors to see
    """

    description: Optional[str] = ""
    global_role: str
    account_deactivated: bool
    editor_config: Optional[Dict] = {}

    # entries: Union[List[ActorEntryRelationOut], EntriesMetaPaginated] = []

    class Config:
        orm_mode = True


class ActorAuthToken(BaseModel):
    access_token: str
    token_type: str
    expiration_date: Union[datetime, date]

    class Config:
        orm_mode = True


class ActorRegisterIn(BaseModel):
    registered_name: str = Field(
        ...,
        description="unique name (registered_name)",
        example="sr_cool",
        min_length=4,
    )
    email: EmailStr = Field(..., description="", example="cool@notcool.de")
    password: SecretStr = Field(example="secret_pwd", min_length=8)
    password_confirm: SecretStr = Field(example="secret_pwd", min_length=8)
    settings: Dict = {}

    class Config(InConfig):
        pass

    @validator("registered_name", pre=True)
    def validate_registered_name(cls, value):
        if value == "visitor":
            raise app.util.exceptions.ApplicationException(
                HTTP_400_BAD_REQUEST, "This username is not allowed"
            )
        if not re.match("^[a-z][a-z0-9_]*$", value):
            raise app.util.exceptions.ApplicationException(
                HTTP_400_BAD_REQUEST, "This username has invalid characters"
            )
        return value

    @validator("email")
    def validate_email(cls, value):
        return value.lower()

    @validator("password_confirm")
    def validate_password(cls, value, values):
        if value != values["password"]:
            raise app.util.exceptions.ApplicationException(
                HTTP_400_BAD_REQUEST, "password and password_confirm do not match"
            )
        return value


class ActorUpdateIn(BaseModel):
    # email: EmailStr = Field(None, description="", example="test@gmail.de")
    public_name: str = Field(
        None, min_length=2, max_length=30, description="public name", example="sr.nice"
    )
    description: Optional[str]
    default_privacy: Optional[Literal["public", "private"]]
    default_license: str = Field(None, example="CC-BY")
    settings: Optional[Dict]

    class Config(InConfig):
        extra = "allow"


class ActorEmailUpdateIn(BaseModel):
    email: EmailStr = Field(None, description="", example="test@gmail.de")
    password: SecretStr = Field(min_length=8)

    @validator("email")
    def validate_email(cls, value):
        return value.lower()


class ActorPasswordUpdateIn(BaseModel):
    actual_password: SecretStr = Field(min_length=8)
    password: SecretStr = Field(min_length=8)
    password_confirm: SecretStr = Field(min_length=8)

    class Config(InConfig):
        pass


class ActorOut(ActorSimpleOut):
    """
    db outs basics dont have lazy loaded stuff
    """

    email: str = ""
    # these 2 can go into settings...
    # default_privacy: str
    # default_license: str
    settings: Dict = {}
    config_share: Dict = {}  # configs that are shared with the user

    class Config:
        orm_mode = True


class ActorLoginOut(ActorAuthToken):
    user: ActorOut
    msg: Optional[str]


class SessionValidation(BaseModel):
    session_valid: bool
    data: Optional[ActorOut]


class ActorTokenValidOut(BaseModel):
    token_valid: bool


class ActorPasswordResetIn(BaseModel):
    code: str
    registered_name: str
    password: str = Field(..., min_length=8)
    password_confirm: str = Field(..., min_length=8)

    class Config(InConfig):
        pass


class ActorCredentialsIn(BaseModel):
    registered_name: str
    password: SecretStr = Field(...)

    @validator("password")
    def validate_password(cls, v, values):
        # TODO actor_sw.is_oauth_user
        if values["registered_name"].startswith("oauth_"):
            return ""
        elif len(v) < 8:
            raise ValueError("ensure this value has at least 8 characters")
        else:
            return v

    class Config(InConfig):
        pass


class EditorConfig(BaseModel):
    global_role: Optional[Literal["user", "editor", "admin"]]  # for in yes, for out no
    domain: Optional[List[str]] = []
    language: Optional[List[str]] = []


# class Actor_Settings(BaseModel):
# 	ui_language: str = "en"
# 	fixed_domain: Union[str, None]
# 	default_license: str
# 	default_privacy: str
