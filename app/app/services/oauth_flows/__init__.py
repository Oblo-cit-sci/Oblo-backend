from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name="orchid",
    server_metadata_url="https://sandbox.orcid.org/.well-known/openid-configuration",
    client_kwargs={"scope": "openid"},
)
