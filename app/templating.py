"""
Shared Jinja2Templates instance. Import `templates` from here in every
router instead of instantiating Jinja2Templates locally — this is the
only place the `label` i18n filter is registered, and template caching
should not be duplicated across routers.
"""
from fastapi.templating import Jinja2Templates

from app.i18n import label
from app.timezone import format_msk_date, format_msk_datetime

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["label"] = label
templates.env.filters["msk_date"] = format_msk_date
templates.env.filters["msk_datetime"] = format_msk_datetime
