import sys
import logging
import structlog

# TODO: Potentially load log level from tts_settings.LOG_LEVEL if needed here
# For now, this provides a JSON logger by default.

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Configures and returns a structlog logger for the TTS service."""
    if not structlog.is_configured(): # Configure once for the service
        # Ensure standard library logging is minimally configured
        if not logging.getLogger().hasHandlers():
            handler = logging.StreamHandler(sys.stdout)
            logging.basicConfig(handlers=[handler], level=logging.INFO)

        structlog.configure(
            processors=[
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(), # Default to JSON for service
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    return structlog.get_logger(name) 