"""
Authentication routes — register, login, me, logout.
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import async_session_factory
from core.deps import get_current_user
from core.security import create_access_token, hash_password, verify_password
from models.company import Company
from models.user import User
from api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest):
    async with async_session_factory() as session:
        # Check email uniqueness
        existing = await session.execute(select(User).where(User.email == body.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Create company
        company = Company(name=body.company_name)
        session.add(company)
        await session.flush()  # get company.id

        # Create user
        user = User(
            email=body.email,
            hashed_password=hash_password(body.password),
            company_id=company.id,
            role="admin",  # first user of company is admin
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    logger.info("User registered", email=body.email, company=body.company_name)
    token = create_access_token(str(user.id), user.email, user.role)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    logger.info("User logged in", email=body.email)
    token = create_access_token(str(user.id), user.email, user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    # Attach company_name so the frontend can display it
    async with async_session_factory() as session:
        result = await session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(User.id == current_user.id)
        )
        user_with_company = result.scalar_one_or_none() or current_user

    company_name = None
    if hasattr(user_with_company, "company") and user_with_company.company:
        company_name = user_with_company.company.name

    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
        company_id=current_user.company_id,
        company_name=company_name,
        created_at=current_user.created_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: User = Depends(get_current_user)):
    """
    Client-side logout — token is stateless (JWT), so server just acknowledges.
    Client must discard the token.
    """
    logger.info("User logged out", email=current_user.email)
    return
