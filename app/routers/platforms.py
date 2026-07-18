from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user, require_role
from app.db import get_db
from app.models import Platform, User
from app.templating import templates

router = APIRouter(tags=["platforms"])


@router.get("/", response_class=HTMLResponse)
def list_platforms(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    platforms = db.scalars(
        select(Platform).options(selectinload(Platform.platform_model)).order_by(Platform.id.desc())
    ).all()
    return templates.TemplateResponse(
        request, "dashboard.html", {"platforms": platforms, "user": user}
    )


# TODO(agent): implement per AGENTS.md roadmap, item 4:
# - POST /platforms                  create platform (require_role("engineer")),
#                                     platform_model_id is mandatory
# - GET  /platforms/{id}             platform detail page: slot checklist built
#                                     from platform_model.slots (quantity vs COUNT
#                                     of active platform_components per
#                                     platform_model_slot_id) + component history
#                                     (including removed_at IS NOT NULL rows) +
#                                     platform_events timeline (see roadmap item 4a)
# - POST /platforms/{id}/components  install a component (create PlatformComponent,
#                                     installed_at=now, verify the part_unit is free,
#                                     set platform_model_slot_id when applicable)
# - POST /platforms/{id}/components/{component_id}/remove
#                                     remove a component (set removed_at=now,
#                                     never delete the row!)
# - POST /platforms/{id}/events      record a milestone (see roadmap item 4a
#                                     and app/models/platform_event.py)
# Every mutation goes through app/services/, with an audit_log entry.
# Remember: for role == "viewer", do not expose platform.customer — all
# user-facing strings in the templates stay Russian regardless.
