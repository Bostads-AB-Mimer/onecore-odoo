"""MIM-1960 — rename the "Ny kundinfo" ack columns onto the customer-message feature.

MIM-1844 added new_customer_info_ack_at / new_customer_info_external_ack_at for
the tenant -> case channel (Mina sidor), keyed on a narrow discriminator
(author odoo@mimer.nu AND an inbox notification). MIM-1960 gives that channel
its own name and a broader discriminator (message_type == 'from_tenant'), so
the columns are renamed rather than duplicated.

Ordering: Odoo runs every applicable version's pre-migration for every
module, THEN init_models() (which creates any new column a field definition
declares), THEN every applicable post-migration
(odoo/modules/loading.py:174 pre -> :194 init_models -> :230 post). 19.0.1.0.5
has no pre-migration at all. So on a real production upgrade (1.0.4 -> 1.0.6),
by the time THIS script runs, neither the old nor the new columns exist yet —
init_models() has not run. Nothing to rename there; this script is a no-op,
and init_models() goes on to create customer_message_ack_at /
customer_message_external_ack_at as fresh NULL columns right after, same as
any other new field.

This MUST be a pre-migration, not a post-migration: if it ran after
init_models(), the new columns would already exist as fresh NULLs, so
`column_exists(cr, TABLE, new)` would already be True, the rename would
silently skip, and every existing acknowledgement would be stranded in an
orphaned new_customer_info_ack_at column with no error raised — silent data
loss.

The only environment where the old columns actually exist when this script
runs is a test/dev database already sitting on the unreleased MIM-1844 build
(19.0.1.0.5 — main is still at 1.0.4 as of writing). There the rename does
fire — and those acks were written under the OLD narrow rule. Task 9's
19.0.1.0.6 post-migration guards its re-baselining UPDATE on both ack columns
being NULL, while its last_customer_message_at backfill is unconditional and
advances the anchor to the newest 'from_tenant' message, including ones the
narrow rule never matched. Left alone, a stale non-NULL ack would keep its
narrow-rule verdict while the anchor moves past it — a long-since-read tenant
message would resurface as unread, exactly the regression this whole
migration exists to prevent. So whenever — and only when — this script
actually renames a column, it also resets both ack columns to NULL, so Task
9's post-migration re-baselines every affected row under the new
discriminator uniformly. This is deliberate: a test environment that lived on
the unreleased 1.0.5 build loses any acks made while on it, and gets them
re-derived fresh by the 1.0.6 post-migration instead of carrying forward a
narrower verdict.

Idempotent and side-effect free everywhere else:
  - Production (1.0.4 -> 1.0.6): the old columns never exist when this runs,
    so no rename fires, so no reset fires. Post-upgrade acknowledgements are
    never at risk — this script never touches a database that has already
    gone through init_models() with the new field definitions.
  - Re-running on an already-migrated database: the old columns are gone (or
    never existed), so no rename fires and no reset fires — an
    acknowledgement made after the upgrade is never wiped.
"""

import logging

from odoo.tools.sql import column_exists, rename_column

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"

RENAMES = (
    ("new_customer_info_ack_at", "customer_message_ack_at"),
    ("new_customer_info_external_ack_at", "customer_message_external_ack_at"),
)


def migrate(cr, version):
    renamed_any = False
    for old, new in RENAMES:
        if column_exists(cr, TABLE, old) and not column_exists(cr, TABLE, new):
            rename_column(cr, TABLE, old, new)
            renamed_any = True
            _logger.info("MIM-1960: renamed %s.%s -> %s", TABLE, old, new)
        else:
            _logger.info(
                "MIM-1960: skipping rename %s.%s -> %s (nothing to do)",
                TABLE,
                old,
                new,
            )

    if not renamed_any:
        return

    # A rename only fires on a database that already carried MIM-1844's
    # narrow-rule acks (see docstring). Reset both columns so Task 9's
    # post-migration re-baselines every affected row under the new,
    # broader discriminator instead of preserving the narrower verdict.
    cr.execute("""
        UPDATE maintenance_request
        SET customer_message_ack_at = NULL,
            customer_message_external_ack_at = NULL
        WHERE customer_message_ack_at IS NOT NULL
           OR customer_message_external_ack_at IS NOT NULL
        """)
    _logger.info(
        "MIM-1960: reset %d row(s) of customer_message_ack_at / "
        "customer_message_external_ack_at to NULL for re-baselining "
        "under the new discriminator.",
        cr.rowcount,
    )
