from datetime import date, datetime
from typing import Optional, List
import enum

# SQLAlchemy Imports
from sqlalchemy import String, Integer, Float, Date, DateTime, func, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

# --- ENUMS (Roles) ---
class UserRole(str, enum.Enum):
    ADMIN = "admin"           # Full Access (Can delete users, view all data)
    USER = "user"             # Standard Access (Can view Stocks)
    SUBSCRIBER = "subscriber" # Paid User (Ad-free experience - Future Scope)

# --- 1. STOCK DATA (Product) ---
class MomentumStock(Base):
    __tablename__ = "momentum_ranks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # From yfinance during scan
    
    # Core Logic Data
    rank_score: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_date: Mapped[Date] = mapped_column(Date)
    
    # New Rank System Columns
    daily_rank_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_rank_score: Mapped[int] = mapped_column(Integer, nullable=True)

    # Top 10 Tracking
    last_top10_date: Mapped[Optional[Date]] = mapped_column(Date, nullable=True)
    top10_hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Strength and Quality Indicators
    risk_score: Mapped[int] = mapped_column(Integer, nullable=True)
    is_volume_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=True)
    is_fundamental_ok: Mapped[bool] = mapped_column(Boolean, nullable=True)

    # Financial Data
    current_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_52_week: Mapped[float] = mapped_column(Float, nullable=True) # This is 52-week low price
    low_52_week_date: Mapped[Date] = mapped_column(Date, nullable=True)
    high_52_week_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_52_week_date: Mapped[Date] = mapped_column(Date, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=func.now(), server_default=func.now())

# --- 2. USER TABLE (RBAC & Auth) ---
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    
    # Login Credentials
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True) # Null if Google Login
    
    # Personal Info (For future Marketing/Ads targeting)
    first_name: Mapped[str] = mapped_column(String(50), nullable=True)
    last_name: Mapped[str] = mapped_column(String(50), nullable=True)
    phone: Mapped[str] = mapped_column(String(15), unique=True, nullable=True, index=True)
    
    # Security & Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)   # Can login?
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False) # OTP verified?
    is_google_user: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Role Based Access Control (RBAC)
    role: Mapped[UserRole] = mapped_column(String, default=UserRole.USER)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=func.now(), server_default=func.now())

    # Relationships
    verifications: Mapped[List["VerificationCode"]] = relationship(back_populates="user", cascade="all, delete-orphan")

# --- 3. OTP SYSTEM (Validation) ---
class VerificationCode(Base):
    """
    Stores OTPs for Email/Phone verification.
    """
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    
    code: Mapped[str] = mapped_column(String(10)) # The OTP (e.g., 583920)
    type: Mapped[str] = mapped_column(String(20)) # "email_verification", "phone_verification", "password_reset"
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    user: Mapped["User"] = relationship(back_populates="verifications")

# --- 4. ERROR LOGGING ---
class Error(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    error_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    error_message: Mapped[str] = mapped_column(String(500))
    error_details: Mapped[dict] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
