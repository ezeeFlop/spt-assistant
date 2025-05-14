import sys
import logging
import structlog

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Configures and returns a structlog logger."""
    if not structlog.is_configured():
        # Ensure standard library logging is minimally configured
        if not logging.getLogger().hasHandlers():
            handler = logging.StreamHandler(sys.stdout)
            # Set default level, can be overridden by environment specific config later if needed
            logging.basicConfig(handlers=[handler], level=logging.INFO)

        structlog.configure(
            processors=[
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                # structlog.dev.ConsoleRenderer(), # For dev
                structlog.processors.JSONRenderer(), # For prod, or if preferred
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    return structlog.get_logger(name) 