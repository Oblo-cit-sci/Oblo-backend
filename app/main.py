import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.settings import env_settings, settings_check
from app.setup import setup_all

print(
    """
**********************
...  ..STARTING.....
       _     _       
  ___ | |__ | | ___ _ __
 /___\|_'__\|_|/___\___ 
 |(*)_|_|*)_|_|_(*)|__
 \___/|_.__/|_|\___/____ 
*******************
"""
)

# todo unfortunately this doesnt help
# I need to rebuild or the env-settings are not reloaded
env_settings.cache_clear()

settings_check()

app = FastAPI(
    title=env_settings().PLATFORM_TITLE,
    description="OpenTEK",  # todo pull it from somewhere
    version="0.9",
    default_response_class=ORJSONResponse,
)

setup_all(app)

if __name__ == "__main__":
    from urllib.parse import urlparse

    uvicorn.run(app, host="0.0.0.0", port=env_settings().PORT)
