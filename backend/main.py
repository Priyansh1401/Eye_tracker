from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

# Simple local SQLite DB; for cloud deploy, switch the DATABASE_URL to
# a managed PostgreSQL/MySQL instance (RDS/Cloud SQL) with the same models.
# TODO: With more time, migrate to PostgreSQL for production scalability
DATABASE_URL = "sqlite:///./blinktracker.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    consent_given_at = Column(DateTime, nullable=True)

    sessions = relationship("BlinkSession", back_populates="user")


class BlinkSession(Base):
    __tablename__ = "blink_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(datetime.UTC))
    ended_at = Column(DateTime, default=lambda: datetime.now(datetime.UTC))
    blink_count = Column(Integer, default=0)
    avg_cpu = Column(Float, default=0.0)
    avg_memory_mb = Column(Float, default=0.0)

    user = relationship("User", back_populates="sessions")


Base.metadata.create_all(bind=engine)


# Auth configuration (demo‑level; for production use env vars and rotation)
SECRET_KEY = "change-me-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    password: str = Field(..., min_length=8, max_length=72)  # bcrypt limit
    consent: bool = True


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str]

    class Config:
        from_attributes = True


class BlinkSessionCreate(BaseModel):
    started_at: datetime
    ended_at: datetime
    blink_count: int
    avg_cpu: float
    avg_memory_mb: float


class BlinkSessionOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime
    blink_count: int
    avg_cpu: float
    avg_memory_mb: float

    class Config:
        from_attributes = True


app = FastAPI(title="WaW Eye Tracker Backend")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Auth helpers

def verify_password(plain_password, hashed_password):
    # Truncate password to 72 bytes as required by bcrypt
    plain_password_bytes = plain_password.encode('utf-8')[:72]
    return bcrypt.checkpw(plain_password_bytes, hashed_password.encode('utf-8'))


def get_password_hash(password):
    # Truncate password to 72 bytes as required by bcrypt
    password_bytes = password.encode('utf-8')[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email=email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception

    user = get_user_by_email(db, email=token_data.email)
    if user is None:
        raise credentials_exception
    return user


# Routes


@app.post("/auth/register", response_model=UserOut)
async def register(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_email(db, user_in.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        consent_given_at=datetime.now(timezone.utc) if user_in.consent else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/me", response_model=UserOut)
async def read_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.post("/blink-sessions", response_model=BlinkSessionOut)
async def create_blink_session(
    session_in: BlinkSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = BlinkSession(
        user_id=current_user.id,
        started_at=session_in.started_at,
        ended_at=session_in.ended_at,
        blink_count=session_in.blink_count,
        avg_cpu=session_in.avg_cpu,
        avg_memory_mb=session_in.avg_memory_mb,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.get("/me/blink-sessions", response_model=List[BlinkSessionOut])
async def list_my_blink_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = (
        db.query(BlinkSession)
        .filter(BlinkSession.user_id == current_user.id)
        .order_by(BlinkSession.started_at.desc())
        .all()
    )
    return sessions


# GDPR Compliance Endpoints
@app.get("/me/export")
async def export_user_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export all user data for GDPR compliance."""
    sessions = (
        db.query(BlinkSession)
        .filter(BlinkSession.user_id == current_user.id)
        .order_by(BlinkSession.started_at.desc())
        .all()
    )

    export_data = {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "consent_given_at": current_user.consent_given_at.isoformat() if current_user.consent_given_at else None,
        },
        "blink_sessions": [
            {
                "id": session.id,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat(),
                "blink_count": session.blink_count,
                "avg_cpu": session.avg_cpu,
                "avg_memory_mb": session.avg_memory_mb,
            }
            for session in sessions
        ],
        "export_date": datetime.now(timezone.utc).isoformat(),
    }

    return export_data


@app.delete("/me/delete")
async def delete_user_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete user account and all associated data for GDPR compliance."""
    # Delete all blink sessions first
    db.query(BlinkSession).filter(BlinkSession.user_id == current_user.id).delete()

    # Delete the user
    db.delete(current_user)
    db.commit()

    return {"message": "Account and all associated data have been deleted successfully"}


@app.get("/")
async def root():
    return {"status": "ok", "message": "WaW Eye Tracker Backend"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
