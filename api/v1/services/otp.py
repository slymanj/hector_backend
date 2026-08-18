import random
from datetime import datetime
from sqlalchemy.orm import Session
from api.v1.models.user import User
from api.utils.redis_utils import redis_client
from api.utils.email_utils import email_utils
from api.utils.settings import settings
import logging

logger = logging.getLogger(__name__)


def _dispatch_email(email: str, otp_code: str, user_name: str, *, password_reset: bool = False) -> None:
    """
    Send OTP email either synchronously (default) or via Celery.

    Celery path only runs when EMAIL_USE_CELERY=true AND a worker is consuming
    the queue; otherwise mail never leaves Redis.
    """
    if settings.EMAIL_USE_CELERY:
        try:
            from api.utils.celery_app import (
                send_otp_email_task,
                send_password_reset_email_task,
            )

            if password_reset:
                send_password_reset_email_task.delay(
                    email=email, otp_code=otp_code, user_name=user_name
                )
            else:
                send_otp_email_task.delay(
                    email=email, otp_code=otp_code, user_name=user_name
                )
            logger.info("OTP email queued via Celery for %s", email)
            return
        except Exception as e:
            logger.warning(
                "Celery queue failed for %s (%s); falling back to sync send",
                email,
                e,
            )

    # Sync path (default) — works with only the API process + Brevo
    if password_reset:
        subject = "Password Reset Request - Hector"
        html = None  # email_utils builds default; custom HTML still in celery task
        # reuse verification template style with custom subject
        email_utils.send_otp_email_sync(
            email,
            otp_code,
            user_name,
            subject=subject,
            html_content=_password_reset_html(user_name, otp_code),
        )
    else:
        email_utils.send_otp_email_sync(email, otp_code, user_name)
    logger.info("OTP email sent synchronously to %s", email)


def _password_reset_html(user_name: str, otp_code: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
      <div style="max-width:600px;margin:0 auto;padding:20px;">
        <h2>Password reset</h2>
        <p>Hello {user_name},</p>
        <p>Use this code to reset your Hector password:</p>
        <p style="font-size:28px;font-weight:bold;letter-spacing:4px;">{otp_code}</p>
        <p>This code expires in 10 minutes.</p>
      </div>
    </body>
    </html>
    """


class OTPService:
    @staticmethod
    def generate_otp() -> str:
        return str(random.randint(100000, 999999))

    @staticmethod
    async def send_verification_otp(db: Session, user: User) -> bool:
        """Generate OTP, store in Redis, send email (sync or Celery)."""
        try:
            otp_code = OTPService.generate_otp()

            stored = await redis_client.set_otp(user.email, otp_code, expires_in=600)
            if not stored:
                logger.warning(
                    "Failed to store OTP in Redis for %s — verification may fail until Redis is up",
                    user.email,
                )

            _dispatch_email(user.email, otp_code, user.name, password_reset=False)
            return True

        except Exception as e:
            logger.error("Failed to send verification OTP for %s: %s", user.email, e)
            raise

    @staticmethod
    async def verify_otp(db: Session, email: str, otp_code: str) -> bool:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise ValueError("User not found")

        is_valid = await redis_client.is_otp_valid(email, otp_code)
        if not is_valid:
            raise ValueError("Invalid or expired OTP code")

        user.is_verified = True
        user.updated_at = datetime.utcnow()
        db.commit()

        await redis_client.delete_otp(email)
        logger.info("User %s verified successfully", email)
        return True

    @staticmethod
    async def resend_otp(db: Session, email: str) -> bool:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise ValueError("User not found")

        if user.is_verified:
            raise ValueError("User is already verified")

        return await OTPService.send_verification_otp(db, user)

    @staticmethod
    async def send_password_reset_otp(db: Session, email: str) -> bool:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            logger.info("Password reset requested for non-existent email: %s", email)
            return True

        try:
            otp_code = OTPService.generate_otp()
            # Store under password_reset:email via set_otp prefix otp:{key}
            key = f"password_reset:{email}"
            stored = await redis_client.set_otp(key, otp_code, expires_in=600)
            if not stored:
                logger.warning("Failed to store password reset OTP in Redis for %s", email)

            _dispatch_email(user.email, otp_code, user.name, password_reset=True)
            return True

        except Exception as e:
            logger.error("Failed to send password reset OTP for %s: %s", email, e)
            raise

    @staticmethod
    async def verify_password_reset_otp(db: Session, email: str, otp_code: str) -> bool:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise ValueError("User not found")

        key = f"password_reset:{email}"
        is_valid = await redis_client.is_otp_valid(key, otp_code)
        if not is_valid:
            raise ValueError("Invalid or expired OTP code")

        logger.info("Password reset OTP verified for %s", email)
        return True

    @staticmethod
    async def complete_password_reset(db: Session, email: str, new_password: str) -> bool:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise ValueError("User not found")

        from api.v1.services.auth import pwd_context

        user.password = pwd_context.hash(new_password)
        user.updated_at = datetime.utcnow()
        db.commit()

        key = f"password_reset:{email}"
        await redis_client.delete_otp(key)
        logger.info("Password reset completed for %s", email)
        return True


otp_service = OTPService()
