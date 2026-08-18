from celery import Celery
from api.utils.settings import settings
from api.utils.email_utils import email_utils
import logging

logger = logging.getLogger(__name__)

celery_app = Celery(
    "hector",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(bind=True, max_retries=3)
def send_otp_email_task(self, email: str, otp_code: str, user_name: str):
    """Celery task to send OTP email"""
    try:
        email_utils.send_otp_email_sync(email, otp_code, user_name)
        logger.info(f"OTP email sent successfully to {email}")
        return {"status": "success", "email": email}
    except Exception as exc:
        logger.error(f"Failed to send OTP email to {email}: {str(exc)}")
        raise self.retry(countdown=30, exc=exc)
    
@celery_app.task(bind=True, max_retries=3)
def send_password_reset_email_task(self, email: str, otp_code: str, user_name: str):
    """Celery task to send password reset OTP email"""
    try:
        subject = "Password Reset Request - Hector"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #DC2626; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ padding: 30px; background: #f9f9f9; border-radius: 0 0 8px 8px; }}
                .otp-code {{ 
                    font-size: 32px; 
                    font-weight: bold; 
                    color: #DC2626; 
                    text-align: center; 
                    margin: 20px 0; 
                    padding: 15px;
                    background: #ffffff;
                    border: 2px dashed #DC2626;
                    border-radius: 8px;
                    letter-spacing: 5px;
                }}
                .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #666; }}
                .warning {{ background: #fed7d7; padding: 10px; border-radius: 4px; border: 1px solid #feb2b2; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Hector - Password Reset</h1>
                </div>
                <div class="content">
                    <h2>Hello {user_name},</h2>
                    <p>We received a request to reset your password for your Hector account. Please use the following OTP code to reset your password:</p>
                    <div class="otp-code">{otp_code}</div>
                    <div class="warning">
                        <strong>Note:</strong> This code will expire in 10 minutes. If you didn't request a password reset, please ignore this email.
                    </div>
                    <p>Best regards,<br>The Hector Team</p>
                </div>
                <div class="footer">
                    <p>&copy; 2024 Hector. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        email_utils.send_otp_email_sync(email, otp_code, user_name, subject, html_content)
        logger.info(f"Password reset email sent successfully to {email}")
        return {"status": "success", "email": email}
    except Exception as exc:
        logger.error(f"Failed to send password reset email to {email}: {str(exc)}")
        raise self.retry(countdown=30, exc=exc)