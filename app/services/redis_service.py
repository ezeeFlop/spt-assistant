import redis.asyncio as redis
from app.core.config import settings
from app.core.logging_config import get_logger
from typing import Optional

logger = get_logger(__name__)

class RedisService:
    def __init__(self, host: str = settings.REDIS_HOST, port: int = settings.REDIS_PORT, db: int = settings.REDIS_DB, password: Optional[str] = settings.REDIS_PASSWORD):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self._redis_client: Optional[redis.Redis] = None

    async def get_redis_client(self) -> redis.Redis:
        """Returns an initialized Redis client, creating one if it doesn't exist."""
        if self._redis_client is None or not await self._redis_client.ping(): # Check connection with ping
            try:
                logger.info(f"Connecting to Redis at {self.host}:{self.port}, DB: {self.db}")
                # Ensure any old client is closed before creating a new one
                if self._redis_client:
                    await self._redis_client.close()
                
                self._redis_client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    auto_close_connection_pool=False,
                    # Adding health check to ensure connections are alive
                    health_check_interval=30 
                )
                await self._redis_client.ping() # Verify connection
                logger.info("Successfully connected to Redis.")
            except redis.exceptions.ConnectionError as e:
                logger.error(f"Failed to connect to Redis: {e}", exc_info=True)
                if self._redis_client: # Attempt to close if partially initialized
                    await self._redis_client.close()
                self._redis_client = None 
                raise
            except Exception as e: # Catch any other exception during connection
                logger.error(f"An unexpected error occurred while connecting to Redis: {e}", exc_info=True)
                if self._redis_client:
                    await self._redis_client.close()
                self._redis_client = None
                raise
        return self._redis_client

    async def publish_message(self, channel: str, message: bytes) -> int:
        """Publishes a message to the specified Redis channel."""
        client = await self.get_redis_client()
        # Client should not be None here due to error handling in get_redis_client, but check for safety
        if not client:
            logger.error("Cannot publish message: Redis client is not available after attempting to connect.")
            raise ConnectionError("Redis client not available for publishing after connection attempt.")
        
        try:
            subscriber_count = await client.publish(channel, message)
            logger.debug(f"Published message to {channel}, {subscriber_count} subscribers.")
            return subscriber_count
        except redis.exceptions.RedisError as e: # Catch specific Redis errors
            logger.error(f"Redis error publishing message to {channel}: {e}", exc_info=True)
            raise
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"Unexpected error publishing message to {channel}: {e}", exc_info=True)
            raise

    async def close_connection(self):
        """Closes the Redis connection if it's open."""
        if self._redis_client:
            logger.info("Closing Redis connection.")
            try:
                await self._redis_client.close()
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}", exc_info=True)
            finally:
                self._redis_client = None

# Global instance of the Redis service
redis_service = RedisService()

# Lifespan events for FastAPI to manage Redis connection
async def startup_redis_client():
    """Initialize Redis client on application startup."""
    logger.info("Application startup: Initializing Redis connection...")
    await redis_service.get_redis_client() # This will establish the connection

async def shutdown_redis_client():
    """Close Redis client on application shutdown."""
    logger.info("Application shutdown: Closing Redis connection...")
    await redis_service.close_connection()
 