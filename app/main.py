from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import (
    auth,
    platforms,
    platform_variants,
    platform_items,
    part_categories,
    firmware_types,
    part_units,
    search,
    users,
)

app = FastAPI(title="Server Tracker")

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(platforms.router)
app.include_router(platform_variants.router)
app.include_router(platform_items.router)
app.include_router(part_categories.router)
app.include_router(firmware_types.router)
app.include_router(part_units.router)
app.include_router(search.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok"}
