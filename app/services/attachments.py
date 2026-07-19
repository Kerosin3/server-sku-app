"""
Business logic for attachments — a file belonging either to a
platform_variant (test-run archives, datasheets — reference docs for
the whole BOM) or to one specific platform_item (a photo, a signed
test report — specific to that physical unit). See
app/models/attachment.py for the exclusive-arc design.

Every function here takes exactly one of platform_variant_id /
platform_item_id, mirroring the DB-level CHECK constraint — callers
pass whichever one they have (see app/routers/platform_variants.py and
app/routers/platform_items.py), never both.

No audit_log entries: reference/documentation data, not inventory
state — same reasoning as platform_variants themselves.

Files are streamed to disk under settings.upload_dir in chunks (not
read into memory whole) and capped at settings.max_upload_size_bytes —
an unbounded upload is a disk-fill denial-of-service vector.
"""
import os
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Attachment, User

_CHUNK_SIZE = 1024 * 1024  # 1 MB


class FileTooLargeError(Exception):
    pass


class EmptyFileError(Exception):
    pass


def _upload_dir() -> Path:
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _owner_filter(*, platform_variant_id: int | None, platform_item_id: int | None):
    assert (platform_variant_id is None) != (platform_item_id is None), "exactly one owner required"
    if platform_variant_id is not None:
        return Attachment.platform_variant_id == platform_variant_id
    return Attachment.platform_item_id == platform_item_id


def list_files(
    db: Session, *, platform_variant_id: int | None = None, platform_item_id: int | None = None
) -> list[Attachment]:
    return list(
        db.scalars(
            select(Attachment)
            .where(_owner_filter(platform_variant_id=platform_variant_id, platform_item_id=platform_item_id))
            .order_by(Attachment.uploaded_at.desc())
        ).all()
    )


def get_file(
    db: Session,
    file_id: int,
    *,
    platform_variant_id: int | None = None,
    platform_item_id: int | None = None,
) -> Attachment | None:
    return db.scalar(
        select(Attachment).where(
            Attachment.id == file_id,
            _owner_filter(platform_variant_id=platform_variant_id, platform_item_id=platform_item_id),
        )
    )


def save_file(
    db: Session,
    *,
    actor: User,
    upload: UploadFile,
    platform_variant_id: int | None = None,
    platform_item_id: int | None = None,
) -> Attachment:
    assert (platform_variant_id is None) != (platform_item_id is None), "exactly one owner required"

    stored_filename = uuid.uuid4().hex
    dest_path = _upload_dir() / stored_filename

    size = 0
    try:
        with open(dest_path, "wb") as dest:
            while chunk := upload.file.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > settings.max_upload_size_bytes:
                    raise FileTooLargeError()
                dest.write(chunk)
    except FileTooLargeError:
        dest_path.unlink(missing_ok=True)
        raise

    if size == 0:
        dest_path.unlink(missing_ok=True)
        raise EmptyFileError()

    attachment = Attachment(
        platform_variant_id=platform_variant_id,
        platform_item_id=platform_item_id,
        original_filename=upload.filename or "file",
        stored_filename=stored_filename,
        content_type=upload.content_type,
        size_bytes=size,
        uploaded_by_id=actor.id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def delete_file(db: Session, attachment: Attachment) -> None:
    path = _upload_dir() / attachment.stored_filename
    db.delete(attachment)
    db.commit()
    # DB row is the source of truth for what "exists"; if the file on
    # disk is somehow already gone, that's not an error worth failing
    # the delete request over.
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def file_path(attachment: Attachment) -> Path:
    return _upload_dir() / attachment.stored_filename


def content_disposition(filename: str) -> str:
    """
    filename is free-text and commonly Cyrillic in this app — HTTP
    header values must be latin-1, so a non-ASCII filename= alone
    crashes. ASCII-safe fallback for old clients, RFC 5987 filename*
    for everything modern (all current browsers). Same fix as the item
    JSON export (app/routers/platform_items.py export_item).
    """
    ascii_fallback = "".join(c if c.isascii() else "_" for c in filename) or "file"
    encoded = quote(filename)
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
