from logging import getLogger

from fastapi import APIRouter

# from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/sse")

logger = getLogger(__name__)

#
# @router.get("/stream")
# async def sse(req: Request, token: str, sw: ServiceWorker = Depends(get_sw)):
#     user = get_actor_by_auth_token(sw.db_session, token)
#
#     async def event_publisher():
#         try:
#             while True:
#                 disconnected = await req.is_disconnected()
#                 if disconnected:
#                     logger.info(f"Disconnecting client {req.client}")
#                     break
#                 news = None
#
#                 if news:
#                     yield news
#                 await asyncio.sleep(30)
#             logger.info(f"Disconnected from client {req.client}")
#         except asyncio.CancelledError as e:
#             logger.info(f"Disconnected from client (via refresh/close) {req.client}")
#             # Do any other cleanup, if any
#             raise e
#
#     return EventSourceResponse(event_publisher())
