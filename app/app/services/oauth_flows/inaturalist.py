from json.decoder import JSONDecodeError
from logging import getLogger
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import httpx

from app.settings import BASE_DIR
from app.util.exceptions import ApplicationException
from app.util.files import JSONPath

logger = getLogger(__name__)

base_url = "https://inaturalist.org"
config_file = "inaturalist.json"

auth_endpoint_params = ["client_id", "response_type"]
token_endpoint_params = [
    "client_id",
    "client_secret",
    "code",
    "redirect_uri",
    "grant_type",
]

inat_paths = {
    "auth_path": "/oauth/authorize",
    "token_path": "/oauth/token",
    "profile_path": "/users/edit",
}

profile_assignment = {
    "username": "login",
    "public_name": "name",
    "profile_page": "uri",
    "description": "description",
    "image": "user_icon_url",
}


# this is a general helper...
def url_add_params(url: str, params: dict) -> str:
    url_parts = list(urlparse(url))
    query = dict(parse_qsl(url_parts[4]))
    query.update(params)
    url_parts[4] = urlencode(query)
    return urlunparse(url_parts)


class INaturalistOAuth:
    def __init__(self, root_oauth_service):
        self.root_oauth_service = root_oauth_service
        self.oauth_service_name = "inaturalist"
        self.profile_assignment = profile_assignment

    def inat_init_redirect(self):
        url = urljoin(base_url, inat_paths["auth_path"])
        config = JSONPath(f"{BASE_DIR}/configs/{config_file}").read()
        params = {param: config[param] for param in auth_endpoint_params}
        params["redirect_uri"] = self.root_oauth_service.redirect_uri
        return url_add_params(url, params)

    def complete_flow(self, redirect_params: dict) -> Tuple[dict, dict]:
        access_token_data = self.inat_get_access_token(redirect_params)
        logger.info("access token obtained")
        if access_token_data:
            access_token = access_token_data["access_token"]  # maybe not hard-coded

            # maybe throws an exception if no user-profile
            user_data = self.get_user_data(access_token)
            print(f"user data from oauth flow obtained")
            logger.info(f"user data from oauth flow obtained")
            if user_data:
                return access_token_data, user_data
        else:
            raise ApplicationException(500, "Did not obtain access token")

    def inat_get_access_token(self, redirect_params: dict):
        url = urljoin(base_url, inat_paths["token_path"])
        config = JSONPath(f"{BASE_DIR}/configs/{config_file}").read()
        data = {}
        for param in token_endpoint_params:
            print(f"checking param {param}")
            if param == "redirect_uri":
                data[param] = self.root_oauth_service.redirect_uri
            elif param in redirect_params:
                data[param] = redirect_params[param]
            elif param in config:
                data[param] = config[param]
            else:
                logger.error(f"Missing parameter to obtain access token: {param}")
                return
        res = httpx.post(url, json=data)
        if res.status_code == 200:
            return res.json()
        else:
            logger.error(
                f"Could not obtain access token from INaturalist. {res.status_code}, {res.json()}"
            )

    def get_user_data(self, access_token: str) -> Optional[dict]:
        url = url_add_params(
            urljoin(base_url, inat_paths["profile_path"]),
            {"access_token": access_token},
        )
        res = httpx.get(url, headers={"Accept": "application/json"})
        if res.status_code == 200:
            try:
                return self.relevant_userdata(res.json())
            except JSONDecodeError as err:
                logger.error("User data cannot be read. response is:...")
                logger.error(res.content)
                print(res.content)
        else:
            logger.error(
                f"Could not obtain user profile from INaturalist. {res.status_code}, {res.json()}"
            )

    def relevant_userdata(self, userdata: dict):
        return {key: userdata[profile_assignment[key]] for key in profile_assignment}
