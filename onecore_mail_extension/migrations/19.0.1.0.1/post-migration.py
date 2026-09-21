"""MIM-2040 — give every existing tenant-facing message a sender label.

onecore_tenant_author_name is written when a message is created, so without
this pass every message already in the database stays NULL and Mina sidor has
nothing to show beside a tenant's entire history.

What it can and cannot reconstruct: the label is derived from who is in
group_external_contractor *now* and which resource group each request belongs
to *now*, because neither is versioned. That is the best available answer, and
freezing it here is the point — from this migration on, the value never moves
again, which is exactly what it could not promise if it were computed on read.

Rows are only ever filled in, never overwritten, so re-running the upgrade over
a database that has already been through it changes nothing.

Order matters: contractor rows are labelled with their resource group first,
then any contractor row whose request could not be resolved gets the bare
label, and everything still NULL falls to Mimer. That way an unrecognised
author is attributed to Mimer rather than to a supplier — the same direction
the write path defaults in.
"""

import logging

_logger = logging.getLogger(__name__)

GROUP_XMLID = "onecore_maintenance_extension.group_external_contractor"

# The write path only ever sees the types a caller asks for; history also holds
# the failure variants create() rewrites those into, so the backfill covers
# both. Kept as a literal rather than derived from the message_type selection:
# adding a new type later must be a deliberate decision about old rows, not
# something this one-off pass silently adopts.
BACKFILL_MESSAGE_TYPES = (
    "receipt_to_tenant",
    "tenant_sms",
    "tenant_mail",
    "tenant_mail_and_sms",
    "tenant_my_pages",
    "failed_tenant_sms",
    "failed_tenant_mail",
    "failed_tenant_mail_and_sms",
    "tenant_mail_ok_and_sms_failed",
    "tenant_mail_failed_and_sms_ok",
)


def contractor_partner_ids(env):
    """Partners whose messages should be attributed to a supplier.

    base.user_root is excluded: security/maintenance.xml puts it in
    group_external_contractor, but anything OdooBot posted is Mimer's own
    automation, not a supplier. The write path makes the same exception.
    """
    from odoo import SUPERUSER_ID

    group = env.ref(GROUP_XMLID, raise_if_not_found=False)
    if not group:
        return []
    contractors = group.sudo().all_user_ids.filtered(lambda u: u.id != SUPERUSER_ID)
    return contractors.partner_id.ids


def backfill_tenant_author_names(env):
    """Fill onecore_tenant_author_name wherever it is still NULL."""
    from odoo.addons.onecore_mail_extension.models.mail_message import (
        TENANT_AUTHOR_CONTRACTOR,
        TENANT_AUTHOR_MIMER,
    )

    cr = env.cr
    partner_ids = contractor_partner_ids(env)

    if partner_ids and "maintenance.team" in env:
        # One statement per resource group rather than a join on the team name:
        # maintenance.team.name is translate=True, i.e. a jsonb column, so SQL
        # would have to pick a language out of the JSON. Teams number in the
        # tens.
        for team in env["maintenance.team"].sudo().search([]):
            cr.execute(
                """UPDATE mail_message m
                      SET onecore_tenant_author_name = %s
                     FROM maintenance_request r
                    WHERE m.res_id = r.id
                      AND m.model = 'maintenance.request'
                      AND m.message_type IN %s
                      AND m.onecore_tenant_author_name IS NULL
                      AND m.author_id IN %s
                      AND r.maintenance_team_id = %s""",
                (
                    f"{TENANT_AUTHOR_CONTRACTOR} - {team.name}",
                    BACKFILL_MESSAGE_TYPES,
                    tuple(partner_ids),
                    team.id,
                ),
            )

    if partner_ids:
        # Contractor-authored rows whose request no longer exists, or that were
        # never on a request at all — never a dangling "Mimers Leverantör - ".
        cr.execute(
            """UPDATE mail_message
                  SET onecore_tenant_author_name = %s
                WHERE message_type IN %s
                  AND onecore_tenant_author_name IS NULL
                  AND author_id IN %s""",
            (TENANT_AUTHOR_CONTRACTOR, BACKFILL_MESSAGE_TYPES, tuple(partner_ids)),
        )

    cr.execute(
        """UPDATE mail_message
              SET onecore_tenant_author_name = %s
            WHERE message_type IN %s
              AND onecore_tenant_author_name IS NULL""",
        (TENANT_AUTHOR_MIMER, BACKFILL_MESSAGE_TYPES),
    )


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    from odoo.addons.onecore_mail_extension.models.mail_message import (
        TENANT_AUTHOR_CONTRACTOR,
    )

    env = api.Environment(cr, SUPERUSER_ID, {})
    backfill_tenant_author_names(env)
    cr.execute(
        """SELECT onecore_tenant_author_name LIKE %s, count(*)
             FROM mail_message
            WHERE message_type IN %s
              AND onecore_tenant_author_name IS NOT NULL
         GROUP BY 1""",
        (f"{TENANT_AUTHOR_CONTRACTOR} - %", BACKFILL_MESSAGE_TYPES),
    )
    counts = dict(cr.fetchall())
    _logger.info(
        "MIM-2040 migration complete: %d tenant-facing message(s) attributed to "
        "a resource group, %d to Mimer.",
        counts.get(True, 0),
        counts.get(False, 0),
    )
