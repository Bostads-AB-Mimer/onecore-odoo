"""Migration for MIM-486 — add the "Återsänd" maintenance stage.

External contractors need to be able to return/reject a request (e.g. cannot
reach the tenant). Fresh installs get the stage from the post_init_hook in
onecore_maintenance_extension/hooks/__init__.py; this migration creates it in
already-installed databases.

Idempotent: safe to re-run, and safe if a stage named "Återsänd" was already
created by hand (it then gets the xml-id and canonical values instead of a
duplicate).
"""
import logging

_logger = logging.getLogger(__name__)

STAGE_XML_ID = "onecore_maintenance_extension.stage_atersand"
STAGE_VALUES = {"name": "Återsänd", "fold": True, "done": False, "sequence": 7}


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    stage = env.ref(STAGE_XML_ID, raise_if_not_found=False)
    if not stage:
        stage = env["maintenance.stage"].search(
            [("name", "=", STAGE_VALUES["name"])], limit=1
        )
        if not stage:
            stage = env["maintenance.stage"].create(STAGE_VALUES)
        module, name = STAGE_XML_ID.split(".", 1)
        env["ir.model.data"].create(
            {
                "name": name,
                "module": module,
                "model": "maintenance.stage",
                "res_id": stage.id,
                # Without noupdate, ir.model.data._process_end deletes the
                # xml-id and its record on the next upgrade of the module.
                "noupdate": True,
            }
        )

    stage.write(STAGE_VALUES)
    if env["res.lang"]._get_data(code="sv_SE"):
        stage.with_context(lang="sv_SE").write({"name": STAGE_VALUES["name"]})

    _logger.info(
        "MIM-486 migration complete: 'Återsänd' stage id=%s (%s)",
        stage.id,
        STAGE_XML_ID,
    )
