"""Backfill performed_date ("Utfört datum") from the stage history.

performed_date is stamped when a request enters Utförd, and the field only
exists since March 2026. Requests performed before that have no date, so the
"Utfört datum" filter undercounts them. stage_id is tracked
(mail.tracking.value), so the moment each request entered Utförd is still in
its chatter.

The rule is the one the workflow applies (MaintenanceWorkflowService): entering
Utförd stamps, any other stage except Avslutad clears, closing keeps. So for a
request in Utförd or Avslutad without a date, what counts is its latest tracked
move into any stage other than Avslutad: if that move went into Utförd, its
time is the date. Two moves in the same second are ordered by message id.
Moves into stages that no longer exist (duplicates merged by
hooks._repair_duplicate_stages) are ignored, as if they were not there.

Left empty: requests closed without passing Utförd (closing also covers
duplicates and requests that turned out not to be needed), and requests whose
stage was never tracked (created directly in the stage, or by an import). The
log line reports how many requests stay empty for either reason.

Idempotent: only rows with no date are touched, and a second run finds none it
can fill.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    performed = env.ref("maintenance.stage_5", raise_if_not_found=False)
    closed = env.ref("maintenance.stage_6", raise_if_not_found=False)
    if not performed or not closed:
        _logger.warning("performed_date backfill: Utförd/Avslutad stage missing, skipped.")
        return
    params = {"performed": performed.id, "closed": closed.id}

    cr.execute(
        """
        WITH last_move AS (
            SELECT DISTINCT ON (m.res_id)
                   m.res_id AS request_id, m.date AS moved_at,
                   t.new_value_integer AS stage_id
            FROM mail_tracking_value t
            JOIN mail_message m ON m.id = t.mail_message_id
            JOIN ir_model_fields f ON f.id = t.field_id
            JOIN maintenance_stage s ON s.id = t.new_value_integer
            WHERE m.model = 'maintenance.request'
              AND f.model = 'maintenance.request' AND f.name = 'stage_id'
              AND t.new_value_integer != %(closed)s
            ORDER BY m.res_id, m.date DESC, m.id DESC
        )
        UPDATE maintenance_request r
        SET performed_date = lm.moved_at
        FROM last_move lm
        WHERE r.id = lm.request_id
          AND lm.stage_id = %(performed)s
          AND r.performed_date IS NULL
          AND r.stage_id IN (%(performed)s, %(closed)s)
        """,
        params,
    )
    dated = cr.rowcount

    cr.execute(
        """
        SELECT count(*) FROM maintenance_request
        WHERE performed_date IS NULL AND stage_id IN (%(performed)s, %(closed)s)
        """,
        params,
    )
    _logger.info(
        "performed_date backfill: %d request(s) dated from the stage history, "
        "%d in Utförd/Avslutad still without a date (closed without passing "
        "Utförd, or no tracked stage change).",
        dated,
        cr.fetchone()[0],
    )
    # Raw SQL: anything already cached would keep the old value.
    env.invalidate_all()
