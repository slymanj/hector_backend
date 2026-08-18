import redis
import json
from api.utils.settings import settings
import logging

logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self):
        try:
            if settings.REDIS_URL:
                self.redis_client = redis.from_url(settings.REDIS_URL)
            else:
                self.redis_client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=settings.REDIS_PASSWORD,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
            self.redis_client.ping()
            logger.info("Redis connection established successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            self.redis_client = None

    async def set_otp(self, email: str, otp_code: str, expires_in: int = 600) -> bool:
        """Store OTP in Redis with expiration (default 10 minutes)"""
        if not self.redis_client:
            logger.error("Redis client not available")
            return False
            
        try:
            key = f"otp:{email}"
            self.redis_client.setex(key, expires_in, otp_code)
            logger.info("OTP stored for user (email redacted)")
            return True
        except Exception as e:
            logger.error(f"Failed to store OTP for {email}: {str(e)}")
            return False

    async def get_otp(self, email: str) -> str:
        """Retrieve OTP from Redis"""
        if not self.redis_client:
            logger.error("Redis client not available")
            return None
            
        try:
            key = f"otp:{email}"
            otp = self.redis_client.get(key)
            return otp
        except Exception as e:
            logger.error(f"Failed to get OTP for {email}: {str(e)}")
            return None

    async def delete_otp(self, email: str) -> bool:
        """Delete OTP from Redis"""
        if not self.redis_client:
            logger.error("Redis client not available")
            return False
            
        try:
            key = f"otp:{email}"
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete OTP for {email}: {str(e)}")
            return False

    async def is_otp_valid(self, email: str, otp_code: str) -> bool:
        """Check if OTP is valid"""
        if not self.redis_client:
            logger.error("Redis client not available")
            return False
            
        stored_otp = await self.get_otp(email)
        
        if isinstance(stored_otp, bytes):
            stored_otp = stored_otp.decode('utf-8')
        
        return stored_otp == otp_code

redis_client = RedisClient()