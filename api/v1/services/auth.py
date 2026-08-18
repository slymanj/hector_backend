import os
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from api.v1.models.user import User
from api.utils.settings import settings
from api.v1.schemas.user import UserCreate, Login, UserResponse, UserUpdate, PasswordChange

from api.db.database import get_db
from passlib.context import CryptContext
from api.v1.services.hedera import create_user_wallet, encrypt_private_key
from api.v1.services.otp import otp_service
import logging

logger = logging.getLogger(__name__)

ENCRYPTION_KEY = settings.PRIVATE_KEY_ENCRYPTION_KEY

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login_swagger")

async def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token for the user.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from JWT token (header or cookie).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Try to get token from header first, then from cookie
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

async def register_user(db: Session, user_data: UserCreate) -> dict:
    """
    Register a new investor with auto-generated custodial Hedera wallet
    and a multi-chain wallet row (ready for BTC/ETH/etc. connections).
    """
    if db.query(User).filter(User.email == user_data.email).first():
        raise ValueError("Email already registered")

    # Never allow public registration as admin
    from api.v1.models.user import UserRole

    # Public registration is always investor (promote roles only via admin/DB)
    role = UserRole.INVESTOR

    try:
        wallet_address, private_key = await create_user_wallet()
        logger.info("Created custodial Hedera wallet for new user")
        encrypted_private_key = encrypt_private_key(private_key, ENCRYPTION_KEY)
        # Drop plaintext key from local scope ASAP
        private_key = None
    except Exception as e:
        logger.error("Failed to create wallet: %s", type(e).__name__)
        raise ValueError("Failed to create user wallet. Please try again.")

    hashed_password = pwd_context.hash(user_data.password)
    new_user = User(
        name=user_data.name,
        email=user_data.email.lower().strip(),
        password=hashed_password,
        role=role,
        wallet_address=wallet_address,
        encrypted_private_key=encrypted_private_key,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_verified=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Mirror custodial HBAR into multi-chain wallets table
    try:
        from api.v1.services.wallet import ensure_custodial_hedera_wallet

        await ensure_custodial_hedera_wallet(
            db, new_user, wallet_address, encrypted_private_key
        )
    except Exception as e:
        logger.warning(f"Could not sync UserWallet row: {e}")

    try:
        await otp_service.send_verification_otp(db, new_user)
        otp_message = (
            "Investor registered successfully. Please check your email for the verification code. "
            "You can connect Bitcoin, Ethereum, and other wallets after login."
        )
    except Exception as e:
        logger.error(f"Failed to send OTP email: {str(e)}")
        otp_message = (
            "User registered successfully, but verification email failed. Please contact support."
        )

    return {
        "message": otp_message,
        "user": UserResponse.model_validate(new_user),
        "wallet_address": wallet_address,
        "is_verified": False,
        "note": "Custodial HBAR wallet created. Connect BTC/ETH/SOL/USDT via POST /api/v1/wallets/connect",
    }

async def login_user(db: Session, login_data: Login, response: Response = None) -> dict:
    """
    Authenticate a user and generate a JWT token.
    """
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user:
        raise ValueError("Invalid email or password")

    hashed_password = str(user.password)
    if not hashed_password or not pwd_context.verify(login_data.password, hashed_password):
        raise ValueError("Invalid email or password")

    if not user.is_verified:
        raise ValueError("Please verify your email before logging in. Check your email for the verification code.")

    access_token_expires = timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    access_token = await create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    if response:
        cookie_kwargs = {
            "key": "token",
            "value": access_token,
            "httponly": True,
            "secure": settings.COOKIE_SECURE,
            "samesite": settings.COOKIE_SAMESITE,
            "max_age": 60 * 60 * settings.ACCESS_TOKEN_EXPIRE_HOURS,
            "path": "/",
        }
        if settings.COOKIE_DOMAIN:
            cookie_kwargs["domain"] = settings.COOKIE_DOMAIN
        response.set_cookie(**cookie_kwargs)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }

async def login_user_swagger(db: Session, form_data: OAuth2PasswordRequestForm, response: Response = None) -> dict:
    """
    Authenticate a user and generate a JWT token for OAuth2 password flow.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user:
        raise ValueError("Invalid email or password")
        
    if not pwd_context.verify(form_data.password, user.password):
        raise ValueError("Invalid email or password")

    if not user.is_verified:
        raise ValueError("Please verify your email before logging in. Check your email for the verification code.")

    access_token_expires = timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    access_token = await create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    if response:
        cookie_kwargs = {
            "key": "token",
            "value": access_token,
            "httponly": True,
            "secure": settings.COOKIE_SECURE,
            "samesite": settings.COOKIE_SAMESITE,
            "max_age": 60 * 60 * settings.ACCESS_TOKEN_EXPIRE_HOURS,
            "path": "/",
        }
        if settings.COOKIE_DOMAIN:
            cookie_kwargs["domain"] = settings.COOKIE_DOMAIN
        response.set_cookie(**cookie_kwargs)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }

async def update_user_profile(
    db: Session, 
    current_user: User, 
    user_update: UserUpdate
) -> User:
    """
    Update user profile information
    """
    update_data = user_update.model_dump(exclude_unset=True)
    
    if not update_data:
        raise ValueError("No data provided for update")
    
    if 'email' in update_data and update_data['email'] != current_user.email:
        existing_user = db.query(User).filter(
            User.email == update_data['email'],
            User.id != current_user.id
        ).first()
        if existing_user:
            raise ValueError("Email already registered")
        
        current_user.is_verified = False
    
    for field, value in update_data.items():
        if value is not None:
            setattr(current_user, field, value)
    
    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    
    logger.info(f"User {current_user.id} profile updated")
    return current_user

async def change_user_password(
    db: Session,
    current_user: User,
    password_change: PasswordChange
) -> bool:
    """
    Change user password after verifying current password
    """
    if not pwd_context.verify(password_change.current_password, current_user.password):
        raise ValueError("Current password is incorrect")
    
    new_hashed_password = pwd_context.hash(password_change.new_password)
    current_user.password = new_hashed_password
    current_user.updated_at = datetime.utcnow()
    
    db.commit()
    logger.info(f"User {current_user.id} password changed")
    return True

async def delete_user_account(
    db: Session,
    current_user: User,
    password: str
) -> bool:
    """
    Delete user account after password verification
    """
    if not pwd_context.verify(password, current_user.password):
        raise ValueError("Password is incorrect")
    
    db.delete(current_user)
    db.commit()
    
    logger.info(f"User {current_user.id} account deleted")
    return True