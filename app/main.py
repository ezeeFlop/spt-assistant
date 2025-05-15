from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

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

# Serve frontend static files
# This needs to be mounted after specific API routes
app.mount("/assets", StaticFiles(directory="app/frontend/assets"), name="frontend-assets")

@app.get("/{full_path:path}")
async def serve_spa_index(request: Request, full_path: str):
    static_frontend_dir = "frontend"
    index_html_path = os.path.join(static_frontend_dir, "index.html")
    
    # Attempt to serve specific files like manifest.json, favicon.ico, etc.
    potential_file_path = os.path.join(static_frontend_dir, full_path)
    if os.path.isfile(potential_file_path):
        return FileResponse(potential_file_path)
        
    # For any other path, serve the main index.html (SPA behavior)
    return FileResponse(index_html_path)

# If you prefer a simpler mount for SPA that handles index.html automatically at root:
# app.mount("/", StaticFiles(directory="static_frontend", html=True), name="spa")
# Ensure this simpler mount is LAST if you use it, so it doesn't override API routes.
# The more specific @app.get("/{full_path:path}") above gives more control. 