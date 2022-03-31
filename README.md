# Oblo backend

## Requirements:

- python 3.9+
- postgresql 10+

## Setup

    $ cd app
    $ python3 -m venv venv
    $ source venv/bin/activate
    $ pip install -r requirements.txt

copy the template envirnment file modify the new config file to your needs:

    $ cp configs/.env configs/.dev.env

alternatively it could be `.prod.env` or `.test.env`

Following variables are required to be defined. The others are optional or
have default values:

    # This should be set outside the env file. Which specifies which file is selected.
    ENV: either 'dev','test' or 'prod' 
    
    HOST= (REQUIRED): Host address (eventually including the port) of the app. (dev-server when frontend is running in development mode)
    e.g. `0.0.0.0` or `https://oblo-server.net`.
    if a development frontend server is running it should be set to that.
    
    PORT: This is only required when the app is started from the main file (default: 8100)
    
    In order to connect to a postgres database the following variables are required:
    
    POSTGRES_HOST= # (REQUIRED) Host address of the postgres database
    POSTGRES_USER= # (REQUIRED) Username for the postgres database
    POSTGRES_PASSWORD= # (REQUIRED) Password of the postgres database
    POSTGRES_DB (REQUIRED)= # Name of the postgres database
    
    FIRST_ADMIN_EMAIL= # (REQUIRED) Email of the first admin user
    FIRST_ADMIN_PASSWORD= # (REQUIRED) Password of the first admin user
    
    EMAIL_ENABLED: (False or True) Set if emails should be sent (default: False)
    EMAIL_SENDER(REQUIRED, when EMAIL_ENABLED):  Name of the sender, including the server.
    EMAIL_ACCOUNT (REQUIRED, when EMAIL_ENABLED): Email address of the sender 
    EMAIL_PWD (REQUIRED, when EMAIL_ENABLED): Password of the email  account
    EMAIL_SSL_SERVER (REQUIRED, when EMAIL_ENABLED): smtp-server of email account
    
    SESSION_SECRET (REQUIRED): A generic secret to be used for session encryption
    
    MAP_DEFAULT_MAP_STYLE= # (REQUIRED)
    MAP_ACCESS_TOKEN= # (REQUIRED)
        
All other variables are optional are described here: 
## Getting the Frontend application

the frontend is a static web application. If not built and run locally the latest version can
be downloaded by:

    $ wget https://opentek.eu/fe_releases/latest.zip
    
It should be in the app folder and named `fe` (or different depending on the environmental variable `APP_DIR`)

Unzip and delete the zip file.

    $ unzip latest.zip
    $ rm latest.zip

The server can now be started with

    $ source venv/bin/activate
    $ export ENV=dev
    $ uvicorn main:app --port=8100

See the [uvicorn settings](https://www.uvicorn.org/settings/) for more configurations.
or use `ENV=prod` to run in production mode. (or `ENV=test` to run in test mode).