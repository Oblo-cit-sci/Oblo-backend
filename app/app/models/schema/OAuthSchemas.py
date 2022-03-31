from typing import Optional, Union

from pydantic import BaseModel, SecretStr, HttpUrl


class ServiceConfig(BaseModel):
    name: str
    client_id: str
    client_secret: SecretStr
    authorization_endpoint: HttpUrl
    token_endpoint: HttpUrl
    userinfo_endpoint: HttpUrl
    server_metadata_url: Optional[HttpUrl]
    client_kwargs: Optional["ServiceConfigKwArgs"]
    # our configs
    service_icon_url: Optional[HttpUrl]
    access_token_as_query_param: Optional[
        bool
    ] = False  # for inat where the token is not in the header but query param
    user_mapping: "UserMapping"

    class Config:
        arbitrary_types_allowed = True


class ServiceConfigKwArgs(BaseModel):
    scope: Optional[str] = None


class UserMapping(BaseModel):
    username: str
    public_name: Optional[
        Union[str, list]
    ]  # could be multiple that are joined together
    profile_path: Optional[str]
    description: Optional[str]
    image: Optional[str]


class OAuthServiceInfo(BaseModel):
    service_name: str
    service_icon_url: Optional[HttpUrl]


ServiceConfig.update_forward_refs()
