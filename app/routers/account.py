from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User
from app.services import users as users_service
from app.templating import templates

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/security-question", response_class=HTMLResponse)
def security_question_form(
    request: Request,
    saved: str = "",
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request, "account_security_question.html", {"user": user, "error": None, "saved": bool(saved)}
    )


@router.post("/security-question", response_class=HTMLResponse)
def security_question_submit(
    request: Request,
    question: str = Form(...),
    answer: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        users_service.set_security_question(db, user=user, question=question, answer=answer)
    except users_service.MissingSecurityQuestionError:
        return templates.TemplateResponse(
            request,
            "account_security_question.html",
            {"user": user, "error": "Укажите и вопрос, и ответ"},
            status_code=400,
        )
    return RedirectResponse(url="/account/security-question?saved=1", status_code=303)
