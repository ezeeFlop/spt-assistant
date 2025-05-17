from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os

from app.api.v1.endpoints import audio
from app.api.v1.endpoints import conversations as conv_endpoints
from app.core.config import settings
from app.middleware.cors import add_cors_middleware
from app.middleware.error_handler import add_error_handling_middleware
from app.middleware.logging import add_request_logging_middleware
from app.services.redis_service import startup_redis_client, shutdown_redis_client

import logging
logger = logging.getLogger(__name__)

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

FRONTEND_DIR = "/app/frontend"
STATIC_ASSETS_DIR = os.path.join(FRONTEND_DIR, "assets")
INDEX_HTML_PATH = os.path.join(FRONTEND_DIR, "index.html")

if os.path.exists(FRONTEND_DIR) and os.path.isdir(FRONTEND_DIR):
    # Mount static assets (JS, CSS, images etc.) under /static_assets
    if os.path.exists(STATIC_ASSETS_DIR) and os.path.isdir(STATIC_ASSETS_DIR):
        app.mount("/assets", StaticFiles(directory=STATIC_ASSETS_DIR), name="static_assets")
        logger.info(f"Serving static assets from {STATIC_ASSETS_DIR}")
    else:
        logger.warning(f"Static assets directory not found: {STATIC_ASSETS_DIR}. Assets might not load correctly.")
        
    # Generate config.js file
    config_js_path = os.path.join(STATIC_ASSETS_DIR, "config.js")
    try:
        with open(config_js_path, "w") as f:
            f.write(f"""window.APP_CONFIG = {{
VITE_API_BASE_URL: '{settings.VITE_API_BASE_URL}',
}};""")
        logger.info(f"Generated frontend config {config_js_path}")
    except IOError as e:
        logger.error(f"Failed to write frontend config {config_js_path}: {e}")

    @app.get("/config.js")
    async def serve_config_js():
        return FileResponse(config_js_path)

    # Catch-all route to serve index.html for SPA routing
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        logger.info(f"Serving SPA {full_path}")
        if os.path.exists(INDEX_HTML_PATH):
            return FileResponse(INDEX_HTML_PATH)
        else:
            # This case should ideally not happen if FRONTEND_DIR exists,
            # but good to handle defensively.
            logger.error(f"index.html not found at {INDEX_HTML_PATH}")
            # Return a simple 404 or a more informative error page if desired
            return JSONResponse(
                status_code=404,
                content={"message": "Frontend entry point not found."},
            )
    logger.info(f"Serving SPA entry point from {INDEX_HTML_PATH}")
else:
    # Only log a warning if not found, as it might be expected in some dev scenarios
    logger.warning(f"Static frontend directory not found or not a directory: {FRONTEND_DIR}. Frontend will not be served by FastAPI.")
# --- End frontend serving section ---
