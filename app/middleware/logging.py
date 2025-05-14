import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
# from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseCallNext # Commented out
# from starlette.types import RequestResponseCallNext # Commented out
from starlette.responses import Response
from typing import Any # ADDED

from app.core.logging_config import get_logger

logger = get_logger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response: # MODIFIED call_next type to Any
        start_time = time.time()
        
        # Log request details (excluding sensitive headers if any)
        log_extra = {
            "method": request.method,
            "url": str(request.url),
            "client_host": request.client.host if request.client else "N/A",
            "client_port": request.client.port if request.client else "N/A",
        }
        # To log headers: logger.info("Incoming request headers", extra={"headers": dict(request.headers)})
        # Be careful with logging headers in production due to sensitive data.

        logger.info(f"Incoming request: {request.method} {request.url}", extra=log_extra)
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            log_extra["status_code"] = response.status_code
            log_extra["process_time_ms"] = round(process_time * 1000, 2)
            logger.info(f"Request finished: {request.method} {request.url} - Status: {response.status_code}", extra=log_extra)
        except Exception as e:
            process_time = time.time() - start_time
            log_extra["process_time_ms"] = round(process_time * 1000, 2)
            log_extra["exception_type"] = type(e).__name__
            logger.error(
                f"Request failed: {request.method} {request.url} - Exception: {type(e).__name__}", 
                exc_info=True, 
                extra=log_extra
            )
            raise e # Re-raise the exception to be caught by global_exception_handler or FastAPI default
        
        return response

def add_request_logging_middleware(app):
    app.add_middleware(RequestLoggingMiddleware) 