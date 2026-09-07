"""MIM-1960 — re-baseline the customer-message acks on the new discriminator.

MIM-1844 detected Mina-sidor messages as "authored by odoo@mimer.nu AND
carrying an inbox notification". MIM-1960 replaces that with
message_type = 'from_tenant', the value onecore's work-order service actually
writes. The new rule matches a WIDER set: a from_tenant message that produced no
inbox notification, or that predates the integration user, was invisible to the
old rule.

MIM-1844's baseline aggregated FROM mail_notification, so such a request yielded
no row and kept NULL acks. Under the new discriminator it lights up as unread —
and, with the new _order, jumps to the top of everyone's kanban. This migration
exists so no historical tenant message resurfaces.

Rule, per request:

    latest_from_tenant := MAX(date) over its message_type='from_tenant' messages
    stays_flagged      := some inbox notification on one of those messages is
                          still unread for a NON-contractor recipient

    ack = NULL               when stays_flagged  -- outstanding, keep it visible
        = latest_from_tenant otherwise           -- already read, stays quiet

customer_message_ack_at is the only column this script writes now. MIM-1960
(commit 906947c, after this script was first written) collapsed the
per-audience ack pair into that single shared column, so there is no second
verdict to keep in lockstep any more — see
`migrations/19.0.1.0.7/pre-migration.py` for the follow-up that merges
whatever a pre-1.0.6 test database already holds in the now-dropped
customer_message_external_ack_at into this same column. Only rows where
customer_message_ack_at is still NULL are touched, so a re-run cannot clobber
an acknowledgement made after the upgrade.

Contractor inbox rows are excluded from the unread test for the reason MIM-1844
documents: their read state says nothing about whether the tenant's message is
still outstanding on the case.

last_customer_message_at is backfilled over the full history regardless of the
verdict, and the stored sort boolean is recomputed from it. Because the acks
are baselined in the same pass, it lands False — history does not affect the
sort. The datetime exists so a future reply on an old thread sorts correctly.
"""

import logging

_logger = logging.getLogger(__name__)

CUSTOMER_MESSAGE_TYPE = "from_tenant"
SORT_FIELDS = ("customer_message_unread",)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    baselined, still_flagged = _baseline_customer_message_acks(env)
    env.registry.clear_cache()
    _logger.info(
        "MIM-1960 migration complete: re-baselined customer-message "
        "acknowledgements on %d request(s); %d kept flagged as unread.",
        baselined,
        still_flagged,
    )


def _baseline_customer_message_acks(env):
    """Seed the shared ack and the sort input from the pre-MIM-1960 read state.

    Returns ``(rows_updated, rows_left_flagged)``.
    """
    external_partner_ids = _external_contractor_partner_ids(env)

    # The aggregate reads mail_message/mail_notification directly, so any
    # pending ORM write (notably is_read, set through the ORM in tests) has to
    # reach the database first.
    env.flush_all()

    # LEFT JOIN, not the inner join MIM-1844 used: a request whose tenant
    # messages produced no inbox notification must still get a row, so it is
    # baselined as read instead of resurfacing. FILTER excludes contractor rows
    # and yields NULL when none qualify, which COALESCE reads as "nothing
    # outstanding".
    env.cr.execute(
        """
        SELECT mm.res_id,
               MAX(mm.date) AS latest,
               COALESCE(
                   BOOL_OR(COALESCE(mn.is_read, FALSE) = FALSE)
                       FILTER (
                           WHERE mn.id IS NOT NULL
                             AND mn.notification_type = 'inbox'
                             AND mn.res_partner_id <> ALL(%s::int[])
                       ),
                   FALSE
               ) AS internal_unread
        FROM mail_message mm
        LEFT JOIN mail_notification mn ON mn.mail_message_id = mm.id
        WHERE mm.model = 'maintenance.request'
          AND mm.res_id IS NOT NULL
          AND mm.date IS NOT NULL
          AND mm.message_type = %s
        GROUP BY mm.res_id
        """,
        (external_partner_ids, CUSTOMER_MESSAGE_TYPE),
    )
    rows = env.cr.fetchall()
    if not rows:
        return 0, 0

    request_ids = [row[0] for row in rows]
    latest_dates = [row[1] for row in rows]
    internal_unread = [row[2] for row in rows]

    # The sort anchor is backfilled unconditionally — it records history, not a
    # verdict, so a future reply on an old thread sorts correctly.
    env.cr.execute(
        """
        UPDATE maintenance_request mr
        SET last_customer_message_at = v.latest
        FROM (
            SELECT *
            FROM unnest(%s::int[], %s::timestamp[]) AS t(id, latest)
        ) v
        WHERE mr.id = v.id
        """,
        (request_ids, latest_dates),
    )

    env.cr.execute(
        """
        UPDATE maintenance_request mr
        SET customer_message_ack_at = CASE
                WHEN v.internal_unread THEN NULL ELSE v.latest
            END
        FROM (
            SELECT *
            FROM unnest(%s::int[], %s::timestamp[], %s::bool[])
                AS t(id, latest, internal_unread)
        ) v
        WHERE mr.id = v.id
          AND mr.customer_message_ack_at IS NULL
        RETURNING mr.id, mr.customer_message_ack_at
        """,
        (request_ids, latest_dates, internal_unread),
    )
    updated = env.cr.fetchall()
    env.invalidate_all()

    _recompute_sort_flags(env, request_ids)

    return len(updated), sum(1 for _id, ack in updated if ack is None)


def _recompute_sort_flags(env, request_ids):
    """Recompute the stored sort booleans.

    The writes above are raw SQL, which bypasses the ORM, so the stored
    computed columns are not refreshed on their own.
    """
    model = env["maintenance.request"]
    records = model.browse(request_ids).exists()
    if not records:
        return
    for field_name in SORT_FIELDS:
        env.add_to_compute(model._fields[field_name], records)
    env.flush_all()


def _external_contractor_partner_ids(env):
    """Partner ids of every external contractor.

    Their inbox rows are excluded from the unread test: their read state carries
    no signal about whether the tenant's message is still outstanding.
    """
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
