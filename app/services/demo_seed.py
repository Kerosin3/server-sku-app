"""
Seeds one fully worked-through example (platform -> variant -> item,
with components, firmware, MAC addresses, stage history, and file
attachments) right after the very first admin account is created —
see app/services/setup.py (web /setup) and app/create_admin.py (CLI).

Goal: whoever stands up a fresh instance immediately has something
real to click through instead of an empty dashboard — this is what
"учёт серверных платформ" actually looks like end to end. Uses the
same service-layer functions a real user's clicks go through (not raw
INSERTs), so it exercises — and stays honest with — the same
validation/business rules as the rest of the app.

Only ever called when needs_setup() was true (see call sites) — i.e.
there is no real data yet to collide with. Safe to delete afterward
through the normal UI (platform/variant/item deletion) if unwanted;
nothing else in the app depends on this data existing.
"""
import io

from sqlalchemy.orm import Session

from app.models import FirmwareType, PartCategory, User
from app.services import attachments as attachments_service
from app.services import firmware_records as firmware_records_service
from app.services import mac_addresses as mac_service
from app.services import platform_events as events_service
from app.services import platform_items as items_service
from app.services import platform_variants as variants_service
from app.services import platforms as platforms_service


class _FakeUpload:
    """Duck-types just enough of fastapi.UploadFile for attachments_service.save_file."""

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(content)


# (slot_name, category_name, quantity, required)
_SLOTS = [
    ("CPU", "CPU", 2, True),
    ("DDR", "DDR", 8, True),
    ("SSD M.2", "SSD M.2", 2, True),
    ("Диск LFF", "Диск LFF", 4, True),
    ("PSU", "PSU", 2, True),
    ("OCP карта", "OCP карта", 1, False),
    ("Райзер", "Райзер", 2, True),
    ("Материнская плата", "Материнская плата", 1, True),
    ("Бэкплейн (передний)", "Бэкплейн (передний)", 1, True),
    ("Бэкплейн (задний)", "Бэкплейн (задний)", 1, False),
    ("IO-плата", "IO-плата", 1, True),
    ("Шасси", "Шасси", 1, True),
]

# (slot_name, article, serial_number_or_None, comment)
_COMPONENTS = [
    ("CPU", "Xeon Gold 6448Y", "DEMO-CPU-0001", ""),
    ("CPU", "Xeon Gold 6448Y", "DEMO-CPU-0002", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0001", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0002", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0003", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0004", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0005", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0006", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0007", ""),
    ("DDR", "Samsung DDR5 64GB RDIMM", "DEMO-DDR-0008", ""),
    ("SSD M.2", "Samsung PM9A3 1.92TB", "DEMO-SSD-0001", ""),
    ("SSD M.2", "Samsung PM9A3 1.92TB", "DEMO-SSD-0002", ""),
    ("Диск LFF", "Seagate Exos X18 18TB", "DEMO-HDD-0001", ""),
    ("Диск LFF", "Seagate Exos X18 18TB", "DEMO-HDD-0002", ""),
    ("Диск LFF", "Seagate Exos X18 18TB", None, "Диск без читаемой этикетки, снят с брака"),
    ("Диск LFF", "Seagate Exos X18 18TB", "DEMO-HDD-0004", ""),
    ("PSU", "Delta 2000W Titanium", "DEMO-PSU-0001", ""),
    ("PSU", "Delta 2000W Titanium", "DEMO-PSU-0002", ""),
    ("Райзер", "СКЮ0012-01", "DEMO-RISER-0001", ""),
    ("Райзер", "СКЮ0012-01", "DEMO-RISER-0002", ""),
    ("Материнская плата", "СКЮ0001", "DEMO-MB-0001", ""),
    ("Бэкплейн (передний)", "СКЮ0003-01", "DEMO-BPF-0001", ""),
    ("IO-плата", "СКЮ0005", None, "Инженерный образец, серийник не присвоен"),
    ("Шасси", "СКЮ0000-4U", "DEMO-CHASSIS-0001", ""),
]


def seed_demo_data(db: Session, *, actor: User) -> None:
    platform = platforms_service.create_platform(
        db, name="DEMO 4U AI Server", description="Демонстрационная платформа — пример для первого запуска"
    )
    variant = variants_service.create_variant(
        db, platform=platform, name="8x GPU Full Config", description="Полная комплектация, 8 GPU, дуал CPU"
    )

    category_ids = {c.name: c.id for c in db.query(PartCategory).filter(PartCategory.platform_variant_id.is_(None))}
    for slot_name, category_name, quantity, required in _SLOTS:
        variants_service.add_slot(
            db,
            variant=variant,
            slot_name=slot_name,
            category_id=category_ids[category_name],
            quantity=quantity,
            required=required,
        )

    firmware_type_ids = {
        f.name: f.id for f in db.query(FirmwareType).filter(FirmwareType.platform_variant_id.is_(None))
    }
    variants_service.add_firmware_requirement(
        db, variant=variant, firmware_type_id=firmware_type_ids["BIOS"], track_backup=True
    )
    variants_service.add_firmware_requirement(
        db, variant=variant, firmware_type_id=firmware_type_ids["BMC"], track_backup=True
    )
    variants_service.add_firmware_requirement(
        db, variant=variant, firmware_type_id=firmware_type_ids["CPLD"], track_backup=False
    )
    variants_service.add_firmware_requirement(
        db, variant=variant, firmware_type_id=firmware_type_ids["Прошивка бэкплейна"], track_backup=False
    )

    variants_service.add_mac_requirement(db, variant=variant, label="BMC", required=True)
    variants_service.add_mac_requirement(db, variant=variant, label="LAN1", required=False)

    attachments_service.save_file(
        db,
        actor=actor,
        platform_variant_id=variant.id,
        upload=_FakeUpload(
            "burn-in-test-results.zip",
            b"DEMO burn-in test report content, 48h stress pass\n" * 40,
            "application/zip",
        ),
    )

    item = items_service.create_item(
        db,
        actor=actor,
        platform_variant_id=variant.id,
        asset_tag="DEMO-0001",
        customer="ООО Тестовый Заказчик",
        location="Стойка A12, юнит 3",
        notes="Демонстрационное изделие — пример для первого запуска",
    )

    variant = variants_service.get_variant(db, variant.id)  # refresh slots relationship
    slot_ids = {s.slot_name: s.id for s in variant.slots}

    part_unit_by_serial: dict[str, int] = {}
    for slot_name, article, serial, comment in _COMPONENTS:
        component = items_service.install_component(
            db,
            actor=actor,
            item=item,
            serial_number=serial,
            platform_variant_slot_id=slot_ids[slot_name],
            article=article,
            comment=comment,
        )
        if serial:
            part_unit_by_serial[serial] = component.part_unit_id

    mb_part_unit_id = part_unit_by_serial["DEMO-MB-0001"]
    bpf_part_unit_id = part_unit_by_serial["DEMO-BPF-0001"]

    firmware_records_service.record_firmware(
        db,
        actor=actor,
        item=item,
        part_unit_id=mb_part_unit_id,
        firmware_type_id=firmware_type_ids["BIOS"],
        image_slot="primary",
        version="2.4.1",
        notes=None,
    )
    firmware_records_service.record_firmware(
        db,
        actor=actor,
        item=item,
        part_unit_id=mb_part_unit_id,
        firmware_type_id=firmware_type_ids["BIOS"],
        image_slot="backup",
        version="2.3.0",
        notes=None,
    )
    firmware_records_service.record_firmware(
        db,
        actor=actor,
        item=item,
        part_unit_id=mb_part_unit_id,
        firmware_type_id=firmware_type_ids["BMC"],
        image_slot="primary",
        version="9.12.3",
        notes=None,
    )
    firmware_records_service.record_firmware(
        db,
        actor=actor,
        item=item,
        part_unit_id=mb_part_unit_id,
        firmware_type_id=firmware_type_ids["BMC"],
        image_slot="backup",
        version="9.11.0",
        notes=None,
    )
    firmware_records_service.record_firmware(
        db,
        actor=actor,
        item=item,
        part_unit_id=mb_part_unit_id,
        firmware_type_id=firmware_type_ids["CPLD"],
        image_slot="primary",
        version="1.02",
        notes=None,
    )
    firmware_records_service.record_firmware(
        db,
        actor=actor,
        item=item,
        part_unit_id=bpf_part_unit_id,
        firmware_type_id=firmware_type_ids["Прошивка бэкплейна"],
        image_slot="primary",
        version="0.9.4",
        notes=None,
    )

    mac_service.add_mac(
        db, actor=actor, item=item, mac_address="AA:BB:CC:00:01:01", label="BMC", part_unit_id=mb_part_unit_id
    )
    mac_service.add_mac(
        db, actor=actor, item=item, mac_address="AA:BB:CC:00:01:02", label="LAN1", part_unit_id=mb_part_unit_id
    )
    mac_service.add_mac(
        db, actor=actor, item=item, mac_address="AA:BB:CC:00:01:FE", label="Chassis-MGMT", part_unit_id=None
    )

    attachments_service.save_file(
        db,
        actor=actor,
        platform_item_id=item.id,
        upload=_FakeUpload("acceptance-photo.jpg", b"FAKE JPEG DEMO CONTENT " * 20, "image/jpeg"),
    )
    attachments_service.save_file(
        db,
        actor=actor,
        platform_item_id=item.id,
        upload=_FakeUpload("test-report-signed.pdf", b"FAKE PDF DEMO CONTENT " * 20, "application/pdf"),
    )

    events_service.record_event(db, actor=actor, item=item, event_type="assembled", notes=None)
    events_service.record_event(db, actor=actor, item=item, event_type="test_started", notes=None)
    events_service.record_event(
        db,
        actor=actor,
        item=item,
        event_type="test_passed_with_remarks",
        notes=(
            "Небольшая царапина на крышке шасси, не влияет на работоспособность. "
            "ГПУ и память прошли 48ч burn-in без ошибок."
        ),
    )
    events_service.record_event(db, actor=actor, item=item, event_type="shipped", notes=None)
    events_service.record_event(
        db,
        actor=actor,
        item=item,
        event_type="service",
        notes="Плановое ТО через 90 дней: чистка от пыли, проверка термопасты, обновление BMC.",
    )
