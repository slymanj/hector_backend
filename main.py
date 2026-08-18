from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import os

from api.utils.settings import settings
from api.utils.security import is_production, safe_error_detail
from api.v1.routes import api_version_one

logger = logging.getLogger(__name__)

# Disable interactive API docs in production to reduce attack surface
_docs_url = "/docs" if settings.ENABLE_DOCS and not is_production() else None
_redoc_url = "/redoc" if settings.ENABLE_DOCS and not is_production() else None
_openapi_url = "/openapi.json" if settings.ENABLE_DOCS and not is_production() else None

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG and not is_production(),
    root_path="/kanec",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Avoid caching authenticated API responses
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if is_production():
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    expose_headers=["Retry-After"],
)

if os.path.isdir("static"):
    app.mount("/static/projects/", StaticFiles(directory="static"), name="static")

app.include_router(api_version_one)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak stack traces or secrets to clients in production."""
    detail = safe_error_detail(exc, "Internal server error")
    return JSONResponse(status_code=500, content={"detail": detail})


@app.get("/")
def healthcheck():
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.VERSION}
