import logging
import sys
import structlog

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Configures and returns a structlog logger."""
    # Configure structlog if not already configured
    if not structlog.is_configured():
        structlog.configure(
            processors=[
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer(), # Use ConsoleRenderer for development
                # TODO: Add structlog.processors.JSONRenderer() for production
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    return structlog.get_logger(name)

# Example usage:
# logger = get_logger(__name__)
# logger.info("This is an informational message", key="value") 