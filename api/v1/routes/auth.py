from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
import logging

from api.db.database import get_db
from api.v1.services.auth import (
    register_user,
    login_user,
    get_current_user,
    login_user_swagger,
    ENCRYPTION_KEY,
    update_user_profile,
    change_user_password,
    delete_user_account,
    create_access_token,
    pwd_context,
)
from api.v1.services.hedera import get_wallet_balance, decrypt_private_key
from api.v1.schemas.user import (
    UserCreate,
    Login,
    UserResponse,
    UserUpdate,
    PasswordChange,
    ForgotPasswordRequest,
    ResetPassword,
    ExportWalletRequest,
)
from api.v1.models.user import User
from api.v1.services.otp import otp_service
from api.utils.settings import settings
from api.utils.rate_limit import rate_limit
from api.utils.security import safe_error_detail

logger = logging.getLogger(__name__)

auth = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookie(response: Response, access_token: str) -> None:
    kwargs = {
        "key": "token",
        "value": access_token,
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "max_age": 60 * 60 * settings.ACCESS_TOKEN_EXPIRE_HOURS,
        "path": "/",
    }
    if settings.COOKIE_DOMAIN:
        kwargs["domain"] = settings.COOKIE_DOMAIN
    response.set_cookie(**kwargs)


@auth.post("/register", status_code=status.HTTP_201_CREATED, response_model=dict)
async def register_user_endpoint(
    user: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    await rate_limit(request, key_prefix="register", limit=5, window_seconds=3600)
    try:
        return await register_user(db, user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_error_detail(e, "Registration failed"),
        )


@auth.post("/login", response_model=dict)
async def login_user_endpoint(
    login: Login,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    await rate_limit(
        request,
        key_prefix="login",
        limit=10,
        window_seconds=300,
        identity=login.email.lower(),
    )
    try:
        return await login_user(db, login, response)
    except ValueError:
        # Generic message — avoid user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )


@auth.post("/login_swagger", response_model=dict)
async def login_user_swagger_endpoint(
    form_data: OAuth2PasswordRequestForm = Depends(),
    response: Response = None,
    db: Session = Depends(get_db),
):
    """OAuth2 password flow for Swagger only (disabled when docs are off)."""
    try:
        return await login_user_swagger(db, form_data, response)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )


@auth.post("/logout")
async def logout_user(response: Response):
    response.delete_cookie(key="token", path="/")
    if settings.COOKIE_DOMAIN:
        response.delete_cookie(key="token", path="/", domain=settings.COOKIE_DOMAIN)
    return {"message": "Logged out successfully"}


@auth.get("/me", response_model=UserResponse)
async def get_current_user_endpoint(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@auth.post("/export-wallet")
async def export_wallet(
    body: ExportWalletRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Export custodial private key — requires password re-authentication.
    High-risk: rate-limited. Disable via ALLOW_WALLET_EXPORT=false.
    """
    if not settings.ALLOW_WALLET_EXPORT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wallet export is disabled on this environment",
        )

    await rate_limit(
        request,
        key_prefix="export_wallet",
        limit=3,
        window_seconds=3600,
        identity=str(current_user.id),
    )

    if not current_user.encrypted_private_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No custodial wallet on this account",
        )

    if not pwd_context.verify(body.password, current_user.password):
        logger.warning("Failed wallet export auth for user_id=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    try:
        decrypted_key = decrypt_private_key(
            current_user.encrypted_private_key, ENCRYPTION_KEY
        )
    except Exception:
        logger.error("Wallet decrypt failed for user_id=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to export wallet",
        )

    logger.info("Wallet export by user_id=%s", current_user.id)
    return {
        "warning": "KEEP THIS PRIVATE KEY SECRET. Anyone with this key can move your funds.",
        "wallet_address": current_user.wallet_address,
        "private_key": decrypted_key,
        "backup_instructions": "Store offline. Do not paste into untrusted websites.",
    }


@auth.post("/verify-email", status_code=status.HTTP_200_OK, response_model=dict)
async def verify_email(
    email: str,
    otp_code: str,
    request: Request,
    db: Session = Depends(get_db),
):
    await rate_limit(request, key_prefix="verify_email", limit=10, window_seconds=600)
    try:
        await otp_service.verify_otp(db, email, otp_code)
        return {"message": "Email verified successfully", "is_verified": True}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@auth.post("/resend-verification", status_code=status.HTTP_200_OK, response_model=dict)
async def resend_verification(
    email: str,
    request: Request,
    db: Session = Depends(get_db),
):
    await rate_limit(
        request,
        key_prefix="resend_otp",
        limit=3,
        window_seconds=900,
        identity=email.lower(),
    )
    try:
        await otp_service.resend_otp(db, email)
    except ValueError:
        pass  # do not reveal whether email exists
    return {"message": "If the account exists, a verification code has been sent"}


@auth.get("/verification-status", response_model=dict)
async def get_verification_status(
    email: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only the authenticated user may query their own verification status."""
    if current_user.email.lower() != email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed",
        )
    return {
        "email": current_user.email,
        "is_verified": current_user.is_verified,
    }


@auth.get("/profile", response_model=dict)
async def get_user_profile(current_user: User = Depends(get_current_user)):
    balance = None
    if current_user.wallet_address:
        try:
            balance = await get_wallet_balance(current_user.wallet_address)
        except Exception:
            balance = None

    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role.value,
        "wallet_address": current_user.wallet_address,
        "balance_hbar": balance,
        "created_at": current_user.created_at,
    }


@auth.put("/profile", response_model=UserResponse)
async def update_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        updated_user = await update_user_profile(db, current_user, user_update)
        return UserResponse.model_validate(updated_user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@auth.patch("/profile", response_model=UserResponse)
async def partial_update_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        updated_user = await update_user_profile(db, current_user, user_update)
        return UserResponse.model_validate(updated_user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@auth.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    password_change: PasswordChange,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await rate_limit(
        request,
        key_prefix="change_password",
        limit=5,
        window_seconds=3600,
        identity=str(current_user.id),
    )
    try:
        await change_user_password(db, current_user, password_change)
        return {"message": "Password changed successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@auth.delete("/account", status_code=status.HTTP_200_OK)
async def delete_account(
    password: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await rate_limit(
        request,
        key_prefix="delete_account",
        limit=3,
        window_seconds=3600,
        identity=str(current_user.id),
    )
    try:
        await delete_user_account(db, current_user, password)
        return {"message": "Account deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@auth.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    await rate_limit(
        request,
        key_prefix="forgot_password",
        limit=5,
        window_seconds=900,
        identity=body.email.lower(),
    )
    try:
        await otp_service.send_password_reset_otp(db, body.email)
    except Exception as e:
        logger.error("Forgot password error: %s", type(e).__name__)
    # Always same response — no email enumeration
    return {"message": "If the email exists, a password reset OTP has been sent"}


@auth.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    reset_data: ResetPassword,
    request: Request,
    db: Session = Depends(get_db),
):
    await rate_limit(
        request,
        key_prefix="reset_password",
        limit=5,
        window_seconds=900,
        identity=reset_data.email.lower(),
    )
    try:
        await otp_service.verify_password_reset_otp(
            db, reset_data.email, reset_data.otp_code
        )
        await otp_service.complete_password_reset(
            db, reset_data.email, reset_data.new_password
        )
        return {"message": "Password reset successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@auth.post("/refresh", response_model=dict)
async def refresh_token(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    try:
        access_token_expires = timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
        access_token = await create_access_token(
            data={"sub": current_user.email}, expires_delta=access_token_expires
        )
        _set_auth_cookie(response, access_token)
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not refresh token",
        )
