# Oblo backend

Read the full docs at [https://oblo-cit-sci.github.io/](https://oblo-cit-sci.github.io/)

## Requirements

- python 3.9+
- postgresql 10+

In order to show the map on the frontend, an account at [mapbox](https://mapbox.com/) is also required.

## Setup

    $ cd app
    $ python3 -m venv venv
    $ source venv/bin/activate
    $ pip install -r requirements.txt

copy the template envirnment file modify the new config file to your needs:

    $ cp configs/.env configs/.dev.env

alternatively it could be `.prod.env` or `.test.env`

All variables which are not commented out need to be defined. Those include variables regarding the database, email of
the admin, mapbox data and the session secret. You can read

All other variables are optional are described here
in [the docs](https://oblo-cit-sci.github.io/pages/setup/#environment-variables)

## Getting the Frontend application

the frontend is a static web application. If not built and run locally the latest version can be downloaded by:

    $ wget https://opentek.eu/fe_releases/latest.zip

It should be in the app folder and named `fe` (or different depending on the environmental variable `APP_DIR`)

Unzip and delete the zip file.

    $ unzip latest.zip
    $ rm latest.zip

The server can now be started with

    $ source venv/bin/activate
    $ export ENV=dev
    $ uvicorn main:app --port=8100

See the [uvicorn settings](https://www.uvicorn.org/settings/) for more configurations. or use `ENV=prod` to run in
production mode. (or `ENV=test` to run in test mode).

The frontend repo can be found [here](https://github.com/Oblo-cit-sci/Oblo-frontend)

## Domains & Template entries

In order to create surveys for data collection you need to define at least one other domain and a template (survey)
entry. A domain can be thought of as a project which includes all related surveys for a topic.  
In the case when you  have only one domain, the platform will go right to the domain page when entering the page. In the
other case, the main page will show all domains and the user can choose which one to enter.

Domains and templates can currently not be created through the frontend but need to be stored in the `domains` folder within the
`init_data` folder (note that domains folder name can be configured through an environmental variable: `INIT_DOMAINS_SUBPATH`).

If you want to jump right in with a demo domain you can use the domain in the following repo:
https://github.com/Oblo-cit-sci/demo-domain-licci
 



