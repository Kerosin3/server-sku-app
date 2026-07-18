from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User
from app.services import search as search_service
from app.templating import templates

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Unified search by component serial number, item asset tag, or MAC
    address — the system's core "where is this thing" workflow. Renders
    an HTML partial for the dashboard's HTMX search box, not JSON.
    """
    results = search_service.search(db, q)
    return templates.TemplateResponse(request, "search_results.html", {"user": user, "q": q, **results})
