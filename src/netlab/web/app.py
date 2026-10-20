"""FastAPI application factory."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup (اگر لازم شد بعداً چیزی اضافه می‌شود)
    yield
    # Shutdown: پاک‌سازی همهٔ منابع netlab در Docker
    from .routes import _nuclear_cleanup
    _nuclear_cleanup()


def create_app() -> FastAPI:
    app = FastAPI(title="NetLab", version=__version__, lifespan=lifespan)
    app.include_router(router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app