from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import time
import uvicorn

from routers import ai_chat, generate, voonix
from services.db import init_db
from services.logger import setup_logging, get_logger
from config import get_settings

settings = get_settings()
setup_logging()
logger = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", environment=settings.environment)
    await init_db()
    logger.info("database_ready")
    yield
    logger.info("shutdown")


app = FastAPI(
    title="MailMind AI — Marketing Intelligence",
    version="3.0.0",
    docs_url="/docs" if settings.debug else None,  # Hide docs in production
    redoc_url=None,
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: restrict to your Lovable domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 2)

    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration,
    )
    return response


# Global error handler — never expose stack traces to users
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong. Please try again."},
    )


# Routers
app.include_router(ai_chat.router, prefix="/api/chat", tags=["AI Chat"])
app.include_router(generate.router, prefix="/api/generate", tags=["Generate"])
app.include_router(voonix.router, prefix="/api/voonix", tags=["Voonix"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "environment": settings.environment,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.debug)
