from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from jose import jwt
from passlib.context import CryptContext

from api.v1.models.user import User
from api.utils.settings import settings
from api.v1.schemas.user import UserCreate, Login

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        Create a JWT access token for the user.
        
        Args:
            data: Dictionary containing user data (e.g., email as subject)
            expires_delta: Optional expiration time delta
            
        Returns:
            str: Encoded JWT token
        """
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    @staticmethod
    def register_user(db: Session, user_data: UserCreate) -> dict:
        """
        Register a new user in the database.
        
        Args:
            db: SQLAlchemy database session
            user_data: Pydantic schema with user registration data
            
        Returns:
            dict: Response with user details
            
        Raises:
            ValueError: If email is already registered
        """
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        if existing_user:
            raise ValueError("Email already registered")

        hashed_password = pwd_context.hash(user_data.password)

        new_user = User(
            name=user_data.name,
            email=user_data.email,
            password=hashed_password,
            role=user_data.role,
            walletAddress=user_data.walletAddress,
            createdAt=datetime.utcnow()
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "message": "User registered successfully",
            "user": {
                "id": new_user.id,
                "name": new_user.name,
                "email": new_user.email,
                "role": new_user.role,
                "walletAddress": new_user.walletAddress,
                "createdAt": new_user.createdAt
            }
        }
    
    @staticmethod
    def login_user(db: Session, login_data: Login) -> dict:
        """
        Authenticate a user and generate a JWT token.
        
        Args:
            db: SQLAlchemy database session
            login_data: Pydantic schema with login credentials
            
        Returns:
            dict: Response with JWT access token
            
        Raises:
            ValueError: If credentials are invalid
        """
        user = db.query(User).filter(User.email == login_data.email).first()
        if not user:
            raise ValueError("Invalid credentials")

        if not pwd_context.verify(login_data.password, str(user.password)):
            raise ValueError("Invalid credentials")

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = AuthService.create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )

        return {"access_token": access_token, "token_type": "bearer"}

