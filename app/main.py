from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.v1.endpoints import audio
from app.api.v1.endpoints import conversations as conv_endpoints
from app.core.config import settings
from app.middleware.cors import add_cors_middleware
from app.middleware.error_handler import add_error_handling_middleware
from app.middleware.logging import add_request_logging_middleware
from app.services.redis_service import startup_redis_client, shutdown_redis_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Context manager for application startup and shutdown events."""
    await startup_redis_client()
    yield
    await shutdown_redis_client()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="Real-time, French-first voice assistant capable of two-way spoken interaction and tool execution.",
    lifespan=lifespan
)

add_request_logging_middleware(app)
add_cors_middleware(app)
add_error_handling_middleware(app)

app.include_router(audio.router, prefix=settings.API_V1_STR, tags=["Audio Streaming"])
app.include_router(conv_endpoints.router, prefix=settings.API_V1_STR, tags=["Conversations"])

@app.get(f"{settings.API_V1_STR}/health", tags=["Health"])
async def health_check():
    """Check the health of the service."""
    return {"status": "ok"} 