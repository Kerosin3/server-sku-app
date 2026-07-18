from fastapi import APIRouter

router = APIRouter(prefix="/part-units", tags=["part_units"])

# TODO(agent): implement per AGENTS.md roadmap, item 2:
# - GET  /part-units             list, filterable by part_type/status
# - POST /part-units             create (require_role("engineer")), check
#                                 serial_number uniqueness -> 409 on conflict
# - GET  /part-units/{id}        detail page + installation history (all
#                                 platform_components rows for this
#                                 part_unit_id, ordered by installed_at desc)
# - POST /part-units/import      bulk CSV import (roadmap item 6)
