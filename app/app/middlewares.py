import time
from logging import getLogger
from os.path import join
from typing import Callable

import orjson
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, RedirectResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.controller_util.auth import session_not_user
from app.models.orm import Actor
from app.services.service_worker import ServiceWorker
from app.settings import env_settings
from app.setup_db import Session
from app.util.consts import PROD
from app.util.my_gzip_middleware import OT_GZipMiddleware

logger = getLogger(__name__)
routes_logger = getLogger("routes")
crashes_logger = getLogger("crashes")

limiter = Limiter(key_func=get_remote_address)


def add_middlewares(app: FastAPI):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[env_settings().HOST]
                      + env_settings().CORS_OTHER_ORIGINS.split(" "),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=[
            "*"
        ],  # "Access-Control-Allow-Headers", "Access-Control-Expose-Headers", "Content-Disposition"],
        expose_headers=["Content-Disposition"],
    )

    # app.add_middleware(
    #     OT_GZipMiddleware, minimum_size=1000, exlude_routes=["/api/sse/stream"]
    # )

    app.add_middleware(
        GZipMiddleware, minimum_size=1000
    )

    def get_actor(req: Request) -> str:
        actor: Actor = dict(req)["state"].get("current_actor")
        if actor:
            return actor.registered_name
        else:
            "visitor"

    # @app.middleware("http")
    # async def current_actor_middleware(request: Request, call_next: Callable, actor = Depends(get_current_actor)):
    #     request.state.current_actor = actor
    #     response = await call_next(request)
    #     return response

    # @app.middleware("http")
    # async def current_actor_middleware(request: Request, call_next: Callable):
    #     print("current_actor_middleware")
    #     return await call_next(request)

    # @app.middleware("http")
    # async def login_required(request: Request, call_next: Callable):

    @app.middleware("http")
    async def db_session_middleware(request: Request, call_next: Callable):
        request.state.db = None
        try:
            # logger.warning(f"{request.url.path}, {not request.url.path.startswith(env_settings().BASE_ROUTER_PREFIX)}")
            # logger.warning(type(request.session.get("user")))
            if not request.url.path.startswith(env_settings().BASE_ROUTER_PREFIX) \
                    and session_not_user(request.session.get("user")):
                if (
                        env_settings().LOGIN_REQUIRED
                        and not request.url.path.startswith("/_nuxt")
                        and not request.url.path.startswith("/api/")
                        and not request.url.path == "/sw.js"
                        and not request.url.path.startswith("/login")
                        and not request.url.path == request.app.docs_url
                        and not request.url.path == "/openapi.json"
                ):
                    return RedirectResponse("/login")
                # temp_session.close()
                return await call_next(request)
            request.state.db = Session()
            if env_settings().LOGIN_REQUIRED and request.url.path.startswith(
                    env_settings().BASE_ROUTER_PREFIX
            ):
                base = env_settings().BASE_ROUTER_PREFIX
                allowed_api_paths = [
                    join(base, path)
                    for path in (
                        "actor/validate_session",
                        "domain/overviews",
                        "basic/init_data",
                        "language/get_language_names",
                        "language/user_guide_url",
                        "basic/domain_basics",
                        "actor/login",
                        "actor/token_login",
                        "actor/"
                    )
                ]
                if (
                        not request.session.get("user")
                        and request.url.path not in allowed_api_paths
                ):
                    return JSONResponse(
                        {"error": {"msg": "You are not logged in"}}, status_code=401
                    )
            # todo for all other pages, it should set into the cookie, the mode that the app is in,
            # so no menu is shown. maybe an about page link. but all routes redirect back to login...

            # logger.warning(f"<<<db_session_middleware {request.state._state}, {request.session} , {request.url}")
            sw: ServiceWorker = ServiceWorker(request.state.db, request)
            request.state.service_worker = sw
            response = await call_next(request)
            request.state.db.close()
            # logger.warning(f">>>db_session_middleware {request.state._state}")
            return response
        except Exception as err:
            crash_infos = {
                "url": str(request.url),
                "method": request.method,
                "actor": "FIX",
            }
            # todo fix use get_actor(request) again
            crashes_logger.exception(orjson.dumps(crash_infos))

            logger.exception(err)
            logger.exception("Error caught by middleware")
            if request.state.db:
                request.state.db.rollback()
                request.state.db.close()
            return JSONResponse(
                jsonable_encoder(err.__dict__),
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            # only in there when route uses dependency
            routes_logger.info(f"{str(request.url)}")
            # return JSONResponse({}, status_code=HTTP_500_INTERNAL_SERVER_ERROR)
            # todo bring back!
            # routes_logger.info(f"{get_actor(request)}: {str(request.url)}")

    if env_settings().TIMING_MIDDLEWARE_ACTIVE:
        @app.middleware("http")
        async def timing_middleware(request: Request, call_next: Callable):
            def current_milli_time():
                return int(round(time.time() * 1000))

            start = current_milli_time()
            response = await call_next(request)
            logger.info(
                f"[{request.method}] - {request.url.path} : {current_milli_time() - start}m."
            )
            return response

    """
    Rate limiter: applied for actor.register actor.login
    """

    def rate_limit_exceeded_handler(
            request: Request, exc: RateLimitExceeded
    ) -> Response:
        response = JSONResponse(
            {"error": {"msg": f"Rate limit exceeded: {exc.detail}"}}, status_code=429
        )
        response = request.app.state.limiter._inject_headers(
            response, request.state.view_rate_limit
        )
        return response

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    """
    Session middleware
    """
    app.add_middleware(
        SessionMiddleware,
        secret_key=env_settings().SESSION_SECRET.get_secret_value(),
        https_only=env_settings().ENV == PROD,
    )
