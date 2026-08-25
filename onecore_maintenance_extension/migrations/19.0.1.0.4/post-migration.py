"""Migration for MIM-1844 — cutover baseline for the "Ny kundinfo" acknowledgements.

MIM-1844 replaced the per-user `new_mimer_notification` (which read
`mail.notification.is_read` for the current user) with two shared per-side
timestamps on the request: `new_customer_info_ack_at` (Mimer) and
`new_customer_info_external_ack_at` (external contractors).

Both columns land NULL on upgrade, and `_compute_has_unread_new_customer_info`
deliberately ignores `is_read`. Without a baseline, every request that ever
received a Mina-sidor inbox notification from odoo@mimer.nu would light up as
unread again — including notifications read long before this release.

The cutover preserves the old read state, and both audiences get the exact same
treatment of in-flight cases: a request keeps NULL acks (so it stays flagged for
Mimer *and* for contractors) when any of its odoo@mimer.nu inbox notifications
is still unread; otherwise both acks are set to the date of the latest such
message, which reads as "everything up to here is acknowledged".

The unread test only looks at *non-contractor* recipients. That is not an
audience split — it is the only read state that ever existed. Contractors never
saw this badge before MIM-1844, so their own inbox rows say nothing about
whether the tenant's message is still outstanding on the case; Mimer's read
state answers that for both sides. Ignoring contractor rows also keeps the old
"any unread notification raises the badge" rule intact for Mimer, exactly as it
behaved before the release.

Requests with no odoo@mimer.nu notification history are left alone: both acks
stay NULL, which the compute already reads as "nothing to acknowledge".

Only rows where *both* columns are still NULL are touched, so a re-run cannot
overwrite acknowledgements made after the upgrade.
"""
import logging

_logger = logging.getLogger(__name__)

MIMER_INTEGRATION_LOGIN = "odoo@mimer.nu"


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    baselined, still_unread = _baseline_new_customer_info_acks(env)
    env.registry.clear_cache()
    _logger.info(
        "MIM-1844 migration complete: baselined 'Ny kundinfo' acknowledgements on "
        "%d request(s); %d kept flagged for both audiences.",
        baselined,
        still_unread,
    )


def _baseline_new_customer_info_acks(env):
    """Seed the two "Ny kundinfo" ack columns from the pre-MIM-1844 read state.

    Both columns get the same verdict, so an in-flight case looks identical to
    Mimer handlers and to external contractors.

    Returns ``(rows_updated, rows_left_flagged)``.
    """
    author_partner_ids = _mimer_integration_partner_ids(env)
    if not author_partner_ids:
        _logger.info(
            "No %s user found — no 'Ny kundinfo' history to baseline.",
            MIMER_INTEGRATION_LOGIN,
        )
        return 0, 0

    external_partner_ids = _external_contractor_partner_ids(env)

    # The aggregate below reads mail_notification/mail_message directly, so any
    # pending ORM write (notably is_read, set through the ORM in tests) has to
    # reach the database first.
    env.flush_all()

    # One aggregate per request: the latest Mina-sidor message, and whether any
    # of its inbox notifications is still unread for a non-contractor recipient.
    # FILTER yields NULL when a request has no internal recipient at all, which
    # COALESCE reads as "nothing outstanding".
    env.cr.execute(
        """
        SELECT mm.res_id,
               MAX(mm.date) AS latest,
               COALESCE(
                   BOOL_OR(COALESCE(mn.is_read, FALSE) = FALSE)
                       FILTER (WHERE mn.res_partner_id <> ALL(%s::int[])),
                   FALSE
               ) AS internal_unread
        FROM mail_notification mn
        JOIN mail_message mm ON mm.id = mn.mail_message_id
        WHERE mm.model = 'maintenance.request'
          AND mm.res_id IS NOT NULL
          AND mm.date IS NOT NULL
          AND mn.notification_type = 'inbox'
          AND mm.author_id = ANY(%s::int[])
        GROUP BY mm.res_id
        """,
        (external_partner_ids, author_partner_ids),
    )
    rows = env.cr.fetchall()
    if not rows:
        return 0, 0

    request_ids = [row[0] for row in rows]
    latest_dates = [row[1] for row in rows]
    internal_unread = [row[2] for row in rows]

    env.cr.execute(
        """
        UPDATE maintenance_request mr
        SET new_customer_info_ack_at = CASE
                WHEN v.internal_unread THEN NULL ELSE v.latest
            END,
            new_customer_info_external_ack_at = CASE
                WHEN v.internal_unread THEN NULL ELSE v.latest
            END
        FROM (
            SELECT *
            FROM unnest(%s::int[], %s::timestamp[], %s::bool[])
                AS t(id, latest, internal_unread)
        ) v
        WHERE mr.id = v.id
          AND mr.new_customer_info_ack_at IS NULL
          AND mr.new_customer_info_external_ack_at IS NULL
        RETURNING mr.id, mr.new_customer_info_ack_at
        """,
        (request_ids, latest_dates, internal_unread),
    )
    updated = env.cr.fetchall()
    env.invalidate_all()
    return len(updated), sum(1 for _id, ack in updated if ack is None)


def _mimer_integration_partner_ids(env):
    """Partner ids of the odoo@mimer.nu integration account Mina sidor posts as."""
    users = (
        env["res.users"]
        .sudo()
        .with_context(active_test=False)
        .search([("login", "=", MIMER_INTEGRATION_LOGIN)])
    )
    return users.partner_id.ids


def _external_contractor_partner_ids(env):
    """Partner ids of every external contractor.

    Their inbox rows are excluded from the unread test: contractors had no
    "Ny kundinfo" badge before MIM-1844, so their read state carries no signal
    about whether the tenant's message is still outstanding."""
    group = env.ref(
        "onecore_maintenance_extension.group_external_contractor",
        raise_if_not_found=False,
    )
    if not group:
        return []
    users = (
        env["res.users"]
        .sudo()
        .with_context(active_test=False)
        .search([("all_group_ids", "in", group.id)])
    )
    return users.partner_id.ids
