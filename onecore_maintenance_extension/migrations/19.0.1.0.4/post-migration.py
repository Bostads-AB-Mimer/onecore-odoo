"""Migration for MIM-1967 — re-run the repaired stage seeding.

19.0.1.0.3 shipped a version of _update_maintenance_stages() that created a
second "Utförd"/"Avslutad" stage on databases where Odoo 19 had dropped the
maintenance.stage_5/stage_6 xml-ids while keeping the records. Databases that
already ran .3 will not replay it (Odoo only runs scripts with
installed_version < script_version), so the fix needs its own script.

Two steps, both idempotent and both no-ops on a healthy database:
  1. the repaired seeding, which adopts existing stages instead of creating
     new ones and repoints stale xml-ids;
  2. a merge of duplicates .3 already created — the oldest record wins, since
     it is the one carrying request history.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    from odoo.addons.onecore_maintenance_extension.hooks import (
        _repair_duplicate_stages,
        _update_maintenance_stages,
    )

    env = api.Environment(cr, SUPERUSER_ID, {})

    _update_maintenance_stages(env)
    _repair_duplicate_stages(env)

    _logger.info("MIM-1967 migration complete: maintenance stages re-asserted")
