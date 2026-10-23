"""Backfill performed_date ("Utfört datum") from the stage history.

performed_date is stamped when a request enters Utförd, and, since this
version, when a request is closed without one (MaintenanceStageManager). The
field only exists since March 2026, so older requests have no date and the
"Utfört datum" filter undercounts them. stage_id is tracked
(mail.tracking.value), so each request's stage moves are still in its chatter.

The rule is the one the workflow applies: entering Utförd stamps, any other
stage except Avslutad clears, closing keeps the date or stamps the closing
time when there is none. So, for requests in Utförd or Avslutad without a date:

1. If the latest tracked move into a stage other than Avslutad went into
   Utförd, its time is the date.
2. Otherwise a request in Avslutad gets its closing time: the latest tracked
   move into Avslutad, else closed_date, else stock's close_date.

Two moves in the same second are ordered by message id. Moves into stages that
no longer exist (duplicates merged by hooks._repair_duplicate_stages) are
ignored. A request in Utförd whose stage was never tracked stays empty; the
log line reports how many.

Idempotent: only rows with no date are touched, and a second run finds none it
can fill.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# Tracked stage moves of maintenance requests, into stages that still exist.
MOVES = """
    SELECT m.res_id AS request_id, m.date AS moved_at, m.id AS message_id,
           t.new_value_integer AS stage_id
    FROM mail_tracking_value t
    JOIN mail_message m ON m.id = t.mail_message_id
    JOIN ir_model_fields f ON f.id = t.field_id
    JOIN maintenance_stage s ON s.id = t.new_value_integer
    WHERE m.model = 'maintenance.request'
      AND f.model = 'maintenance.request' AND f.name = 'stage_id'
"""


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    performed = env.ref("maintenance.stage_5", raise_if_not_found=False)
    closed = env.ref("maintenance.stage_6", raise_if_not_found=False)
    if not performed or not closed:
        _logger.warning("performed_date backfill: Utförd/Avslutad stage missing, skipped.")
        return
    params = {"performed": performed.id, "closed": closed.id}

    # 1. Performed: the latest move other than closing went into Utförd.
    cr.execute(
        f"""
        WITH last_move AS (
            SELECT DISTINCT ON (request_id) request_id, moved_at, stage_id
            FROM ({MOVES}) moves
            WHERE stage_id != %(closed)s
            ORDER BY request_id, moved_at DESC, message_id DESC
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
    from_utford = cr.rowcount

    # 2. Closed without passing Utförd (since): the closing time.
    cr.execute(
        f"""
        WITH last_close AS (
            SELECT DISTINCT ON (request_id) request_id, moved_at
            FROM ({MOVES}) moves
            WHERE stage_id = %(closed)s
            ORDER BY request_id, moved_at DESC, message_id DESC
        )
        UPDATE maintenance_request r
        SET performed_date = c.closed_at
        FROM (
            SELECT u.id, coalesce(lc.moved_at, u.closed_date, u.close_date::timestamp) AS closed_at
            FROM maintenance_request u
            LEFT JOIN last_close lc ON lc.request_id = u.id
            WHERE u.performed_date IS NULL AND u.stage_id = %(closed)s
        ) c
        WHERE r.id = c.id AND c.closed_at IS NOT NULL
        """,
        params,
    )
    from_closing = cr.rowcount

    cr.execute(
        """
        SELECT count(*) FROM maintenance_request
        WHERE performed_date IS NULL AND stage_id IN (%(performed)s, %(closed)s)
        """,
        params,
    )
    _logger.info(
        "performed_date backfill: %d request(s) dated from their move into "
        "Utförd, %d closed without passing Utförd dated with their closing "
        "time, %d in Utförd/Avslutad still without a date.",
        from_utford,
        from_closing,
        cr.fetchone()[0],
    )
    # Raw SQL: anything already cached would keep the old value.
    env.invalidate_all()
