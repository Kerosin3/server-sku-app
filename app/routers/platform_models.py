from fastapi import APIRouter

router = APIRouter(prefix="/platform-models", tags=["platform_models"])

# TODO(agent): manage the "constructor" — the as-planned reference
# configuration for platform models.
# - GET  /platform-models              list platform models
# - POST /platform-models              create a model (require_role — decide
#                                       "admin" vs "engineer" with the user)
# - GET  /platform-models/{id}         model detail page with its slot list
# - POST /platform-models/{id}/slots   add a slot to the constructor
#                                       (slot_name, category, part_type_id?,
#                                       quantity, required)
#
# Usage when assembling a platform (see platforms roadmap item 4):
# on the platform detail page, load platform_model.slots and for each slot
# show: quantity required vs COUNT of platform_components where
# platform_model_slot_id = X AND removed_at IS NULL — giving the engineer
# a completeness checklist instead of a free-form input.
