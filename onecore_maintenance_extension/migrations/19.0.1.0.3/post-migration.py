"""Migration for MIM-486 — add the "Återsänd" maintenance stage.

Fresh installs get the stage from the post_init_hook; this migration brings
already-installed databases to the same state by calling the same
_update_maintenance_stages() the hook uses (idempotent, keyed on xml-id, and
it re-asserts canonical values and sv_SE names on the existing stages).

The only extra step is an adoption guard: if an "Återsänd" stage was created
by hand before this release it has no xml-id, and the hook would create a
duplicate — so we attach the xml-id to the existing record first.
"""
import logging

_logger = logging.getLogger(__name__)

STAGE_XML_ID = "onecore_maintenance_extension.stage_atersand"


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    from odoo.addons.onecore_maintenance_extension.hooks import (
        _update_maintenance_stages,
    )

    env = api.Environment(cr, SUPERUSER_ID, {})

    if not env.ref(STAGE_XML_ID, raise_if_not_found=False):
        hand_made = env["maintenance.stage"].search(
            [("name", "=", "Återsänd")], limit=1
        )
        if hand_made:
            module, name = STAGE_XML_ID.split(".", 1)
            env["ir.model.data"].create(
                {
                    "name": name,
                    "module": module,
                    "model": "maintenance.stage",
                    "res_id": hand_made.id,
                    "noupdate": True,
                }
            )

    _update_maintenance_stages(env)

    stage = env.ref(STAGE_XML_ID)
    _logger.info(
        "MIM-486 migration complete: 'Återsänd' stage id=%s (%s)",
        stage.id,
        STAGE_XML_ID,
    )
