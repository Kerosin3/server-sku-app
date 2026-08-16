from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.templating import templates
from app.routers import (
    account,
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

app = FastAPI(title="Server SKU Tracker")

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(account.router)
app.include_router(platforms.router)
app.include_router(platform_variants.router)
app.include_router(platform_items.router)
app.include_router(part_categories.router)
app.include_router(firmware_types.router)
app.include_router(part_units.router)
app.include_router(search.router)
app.include_router(users.router)


# Russian labels for the HTTPExceptions the routers raise. exc.detail is
# never shown: it's English technical text (see the language convention
# in AGENTS.md), useful in logs, not to the person at the screen.
_ERROR_MESSAGES = {
    403: "Недостаточно прав для этого действия.",
    404: "Страница или объект не найдены.",
    409: "Действие невозможно в текущем состоянии — обновите страницу и попробуйте снова.",
}
_DEFAULT_ERROR_MESSAGE = "Не удалось выполнить запрос."


@app.exception_handler(StarletteHTTPException)
def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """
    Without this, an unauthenticated visit to any page returns the raw
    JSON {"detail": "Not authenticated"} — FastAPI's default. The UI is
    server-rendered and Russian end-to-end, so 401 sends the visitor to
    the login page and everything else renders error.html.

    Registered on Starlette's HTTPException rather than FastAPI's, since
    FastAPI's subclasses it — this catches both. RequestValidationError
    (422, e.g. a form posted without a required field) is a separate
    FastAPI exception class and still returns JSON; that only happens
    for requests the UI's own forms can't produce.
    """
    if exc.status_code == 401:
        # An htmx request swaps the response into a fragment target, so
        # returning the login page here would paste a whole page into
        # e.g. the search-results div. HX-Redirect makes htmx navigate
        # the browser instead.
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse(url="/login", status_code=303)

    # No `user` in the context on purpose: this handler has no DB
    # session, and base.html renders the nav only when `user` is set —
    # so the error page shows a bare header plus a link home.
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exc.status_code,
            "message": _ERROR_MESSAGES.get(exc.status_code, _DEFAULT_ERROR_MESSAGE),
        },
        status_code=exc.status_code,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
