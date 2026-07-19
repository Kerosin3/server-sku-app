import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.config import settings
from app.db import get_db
from app.i18n import PLATFORM_EVENT_TYPES
from app.models import Attachment, PlatformItem, PlatformVariant, User
from app.services import attachments as attachments_service
from app.services import export as export_service
from app.services import firmware_records as firmware_records_service
from app.services import mac_addresses as mac_service
from app.services import platform_events as events_service
from app.services import platform_items as items_service
from app.services import platform_variants as variants_service
from app.templating import templates

router = APIRouter(tags=["platform_items"])


def _get_variant_or_404(db: Session, variant_id: int) -> PlatformVariant:
    variant = variants_service.get_variant(db, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Platform variant not found")
    return variant


def _get_item_or_404(db: Session, item_id: int) -> PlatformItem:
    item = items_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Platform item not found")
    return item


def _get_item_file_or_404(db: Session, item: PlatformItem, file_id: int) -> Attachment:
    attachment = attachments_service.get_file(db, file_id, platform_item_id=item.id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="File not found")
    return attachment


def _detail_context(item: PlatformItem, user: User, error: str | None = None) -> dict:
    return {
        "user": user,
        "item": item,
        "checklist": items_service.slot_checklist(item),
        "can_edit_components": item.status in items_service.EDITABLE_STATUSES,
        "error": error,
    }


def _stages_context(db: Session, item: PlatformItem, user: User, error: str | None = None) -> dict:
    return {
        "user": user,
        "item": item,
        "event_types": PLATFORM_EVENT_TYPES,
        "recent_events": events_service.list_events(db, item)[:5],
        "error": error,
    }


def _firmware_mac_context(db: Session, item: PlatformItem, user: User, error: str | None = None) -> dict:
    installed_components = [c for c in item.components if c.removed_at is None]
    # Firmware lives on in-house boards (motherboard, backplane, ...),
    # not on purchased commodity parts (CPU, RAM, PSU, ...) — restrict
    # the firmware-recording target to "custom"-group components so a
    # CPU/PSU/etc. never shows up as a place to record BIOS/BMC/CPLD.
    # MAC ownership isn't restricted this way: a MAC can legitimately be
    # on a purchased NIC card too.
    firmware_eligible_components = [
        c for c in installed_components if c.part_unit.part_type.category.group == "custom"
    ]
    return {
        "user": user,
        "item": item,
        "installed_components": installed_components,
        "firmware_eligible_components": firmware_eligible_components,
        "firmware_checklist": firmware_records_service.firmware_checklist(db, item),
        "mac_checklist": mac_service.mac_checklist(db, item),
        "error": error,
    }


@router.get("/variants/{variant_id}/items/new", response_class=HTMLResponse)
def new_item_form(
    request: Request,
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    return templates.TemplateResponse(
        request, "item_form.html", {"user": user, "variant": variant, "error": None}
    )


@router.post("/variants/{variant_id}/items", response_class=HTMLResponse)
def create_item(
    request: Request,
    variant_id: int,
    asset_tag: str = Form(...),
    customer: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    variant = _get_variant_or_404(db, variant_id)
    try:
        item = items_service.create_item(
            db,
            actor=user,
            platform_variant_id=variant_id,
            asset_tag=asset_tag,
            customer=customer,
            location=location,
            notes=notes,
        )
    except items_service.AssetTagTakenError:
        return templates.TemplateResponse(
            request,
            "item_form.html",
            {"user": user, "variant": variant, "error": "Изделие с таким asset tag уже существует"},
            status_code=409,
        )
    return RedirectResponse(url=f"/items/{item.id}", status_code=303)


@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(request, "item_detail.html", _detail_context(item, user))


@router.post("/items/{item_id}/delete", response_class=HTMLResponse)
def delete_item(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    variant_id = item.platform_variant_id
    try:
        items_service.delete_item(db, actor=user, item=item)
    except items_service.ItemShippedError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(item, user, error="Изделие уже отгружено — удалить нельзя"),
            status_code=409,
        )
    return RedirectResponse(url=f"/variants/{variant_id}", status_code=303)


@router.get("/items/{item_id}/export")
def export_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    data = export_service.export_item(db, item, include_customer=user.role != "viewer")
    body = json.dumps(data, indent=2, ensure_ascii=False)
    # asset_tag is free-text and commonly Cyrillic in this app — HTTP header
    # values must be latin-1, so a non-ASCII filename= alone crashes with
    # UnicodeEncodeError. ASCII-safe fallback for old clients, RFC 5987
    # filename* for everything modern (all current browsers).
    ascii_fallback = "".join(c if c.isascii() else "_" for c in item.asset_tag) or "item"
    encoded = quote(item.asset_tag)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}.json"; filename*=UTF-8\'\'{encoded}.json'
            )
        },
    )


@router.post("/items/{item_id}/files", response_class=HTMLResponse)
def upload_item_file(
    request: Request,
    item_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        attachments_service.save_file(db, actor=user, platform_item_id=item.id, upload=file)
    except attachments_service.EmptyFileError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request, "item_detail.html", _detail_context(item, user, error="Файл пустой"), status_code=400
        )
    except attachments_service.FileTooLargeError:
        item = _get_item_or_404(db, item_id)
        limit_mb = settings.max_upload_size_bytes // (1024 * 1024)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(item, user, error=f"Файл слишком большой — лимит {limit_mb} МБ"),
            status_code=400,
        )
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.get("/items/{item_id}/files/{file_id}")
def download_item_file(
    item_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    attachment = _get_item_file_or_404(db, item, file_id)
    return FileResponse(
        path=attachments_service.file_path(attachment),
        media_type=attachment.content_type or "application/octet-stream",
        headers={"Content-Disposition": attachments_service.content_disposition(attachment.original_filename)},
    )


@router.post("/items/{item_id}/files/{file_id}/delete", response_class=HTMLResponse)
def delete_item_file(
    item_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    item = _get_item_or_404(db, item_id)
    attachment = _get_item_file_or_404(db, item, file_id)
    attachments_service.delete_file(db, attachment)
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.get("/items/{item_id}/stages", response_class=HTMLResponse)
def item_stages(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(request, "item_stages.html", _stages_context(db, item, user))


@router.get("/items/{item_id}/history", response_class=HTMLResponse)
def item_history(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(
        request,
        "item_history.html",
        {
            "user": user,
            "item": item,
            "removed": items_service.removed_components(item),
            "events": events_service.list_events(db, item),
        },
    )


@router.post("/items/{item_id}/events", response_class=HTMLResponse)
def add_event(
    request: Request,
    item_id: int,
    event_type: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        events_service.record_event(db, actor=user, item=item, event_type=event_type, notes=notes)
    except events_service.InvalidEventTypeError:
        raise HTTPException(status_code=400, detail="Unknown event_type")
    except events_service.RemarksRequiredError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_stages.html",
            _stages_context(db, item, user, error="Опишите замечания в заметке"),
            status_code=400,
        )
    except events_service.PrerequisiteNotMetError as exc:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_stages.html",
            _stages_context(db, item, user, error=exc.message),
            status_code=409,
        )
    return RedirectResponse(url=f"/items/{item_id}/stages", status_code=303)


@router.post("/items/{item_id}/details", response_class=HTMLResponse)
def update_item_details(
    request: Request,
    item_id: int,
    customer: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    items_service.update_details(db, actor=user, item=item, customer=customer, location=location, notes=notes)
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/components", response_class=HTMLResponse)
def install_component(
    request: Request,
    item_id: int,
    serial_number: str = Form(""),
    platform_variant_slot_id: int = Form(...),
    article: str = Form(""),
    comment: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        items_service.install_component(
            db,
            actor=user,
            item=item,
            serial_number=serial_number,
            platform_variant_slot_id=platform_variant_slot_id,
            article=article,
            comment=comment,
        )
    except items_service.SlotNotFoundError:
        raise HTTPException(status_code=400, detail="Unknown platform_variant_slot_id")
    except items_service.ComponentsLockedError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(
                item,
                user,
                error="Изделие укомплектовано — чтобы менять состав, сначала отметьте «Разукомплектовка» на странице этапов",
            ),
            status_code=409,
        )
    except items_service.CommentRequiredError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(
                item,
                user,
                error="Серийный номер не указан — напишите комментарий, что это за деталь",
            ),
            status_code=400,
        )
    except items_service.ArticleRequiredError:
        item = _get_item_or_404(db, item_id)
        error = (
            f"Деталь с серийным номером «{serial_number}» не найдена — укажите артикул, чтобы завести новую"
            if serial_number.strip()
            else "Укажите артикул, чтобы завести новую деталь без серийного номера"
        )
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(item, user, error=error),
            status_code=400,
        )
    except items_service.PartUnitAlreadyInstalledError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(item, user, error="Эта деталь уже установлена в другом изделии"),
            status_code=409,
        )
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/components/{component_id}/remove", response_class=HTMLResponse)
def remove_component(
    request: Request,
    item_id: int,
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        items_service.remove_component(db, actor=user, item=item, component_id=component_id)
    except items_service.ComponentNotActiveError:
        raise HTTPException(status_code=409, detail="Component not active on this item")
    except items_service.ComponentsLockedError:
        item = _get_item_or_404(db, item_id)
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            _detail_context(
                item,
                user,
                error="Изделие укомплектовано — чтобы менять состав, сначала отметьте «Разукомплектовка» на странице этапов",
            ),
            status_code=409,
        )
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.get("/items/{item_id}/firmware-mac", response_class=HTMLResponse)
def item_firmware_mac(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(request, "item_firmware_mac.html", _firmware_mac_context(db, item, user))


@router.post("/items/{item_id}/firmware", response_class=HTMLResponse)
def record_firmware(
    request: Request,
    item_id: int,
    part_unit_id: int = Form(...),
    firmware_type_id: int = Form(...),
    image_slot: str = Form("primary"),
    version: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        firmware_records_service.record_firmware(
            db,
            actor=user,
            item=item,
            part_unit_id=part_unit_id,
            firmware_type_id=firmware_type_id,
            image_slot=image_slot,
            version=version,
            notes=notes,
        )
    except firmware_records_service.PartUnitNotInstalledError:
        error = "Эта деталь не установлена в изделии"
    except firmware_records_service.PurchasedPartCannotCarryFirmwareError:
        error = "Прошивка записывается на платы собственной разработки, а не на покупные детали"
    except firmware_records_service.FirmwareTypeNotRequiredError:
        error = "Этот тип прошивки не задан для данного исполнения"
    except firmware_records_service.BackupNotTrackedError:
        error = "Для этого типа прошивки резервный образ не отслеживается"
    else:
        return RedirectResponse(url=f"/items/{item_id}/firmware-mac", status_code=303)

    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(
        request, "item_firmware_mac.html", _firmware_mac_context(db, item, user, error=error), status_code=400
    )


@router.post("/items/{item_id}/mac", response_class=HTMLResponse)
def add_mac(
    request: Request,
    item_id: int,
    mac_address: str = Form(...),
    label: str = Form(""),
    part_unit_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        mac_service.add_mac(
            db,
            actor=user,
            item=item,
            mac_address=mac_address,
            label=label,
            part_unit_id=int(part_unit_id) if part_unit_id else None,
        )
    except mac_service.InvalidMacFormatError:
        error = "Некорректный формат MAC-адреса"
    except mac_service.MacAddressTakenError:
        error = "Такой MAC-адрес уже зарегистрирован"
    except mac_service.PartUnitNotInstalledError:
        error = "Эта деталь не установлена в изделии"
    else:
        return RedirectResponse(url=f"/items/{item_id}/firmware-mac", status_code=303)

    item = _get_item_or_404(db, item_id)
    return templates.TemplateResponse(
        request, "item_firmware_mac.html", _firmware_mac_context(db, item, user, error=error), status_code=400
    )


@router.post("/items/{item_id}/mac/{mac_id}/remove", response_class=HTMLResponse)
def remove_mac(
    request: Request,
    item_id: int,
    mac_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    item = _get_item_or_404(db, item_id)
    try:
        mac_service.remove_mac(db, actor=user, item=item, mac_id=mac_id)
    except mac_service.MacNotFoundError:
        raise HTTPException(status_code=404, detail="MAC address not found on this item")
    return RedirectResponse(url=f"/items/{item_id}/firmware-mac", status_code=303)
