from fastapi import Request, status
from fastapi.responses import JSONResponse
from app.core.logging_config import get_logger

logger = get_logger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to catch unhandled exceptions and return a JSON response.
    """
    logger.error(f"Unhandled exception for request {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred.", "error_type": type(exc).__name__},
    )

def add_error_handling_middleware(app):
    app.add_exception_handler(Exception, global_exception_handler) 