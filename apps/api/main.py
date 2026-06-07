from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from apps.api.limiter import limiter
from apps.api.routers import chat, entity, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    from observability.setup import setup_telemetry
    setup_telemetry("finagent-api")
    yield


app = FastAPI(
    title="FinAgent Compliance API",
    description="AML / PEP / sanctions investigation platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(chat.router)
app.include_router(entity.router)
app.include_router(search.router)
