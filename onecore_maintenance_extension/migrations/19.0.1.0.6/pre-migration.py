"""MIM-1960 — rename the "Ny kundinfo" ack columns onto the customer-message feature.

MIM-1844 added new_customer_info_ack_at / new_customer_info_external_ack_at for
the tenant -> case channel (Mina sidor). MIM-1960 gives that channel its own
name, so the columns are renamed rather than duplicated: values carry over
verbatim and MIM-1844's cutover baseline stays valid.

Two starting states reach this migration, and both converge because Odoo runs
intermediate version migrations in sequence:

  - production at 19.0.1.0.4 -> 19.0.1.0.5 creates the columns, then this runs
  - a test environment already at 19.0.1.0.5 -> only this runs

Hence the existence guards: the rename must be a no-op if it has already
happened, and must not fail if the old columns were never created.

This has to be a PRE-migration so the ORM finds the new column names when it
loads the updated field definitions.
"""
import logging

_logger = logging.getLogger(__name__)

RENAMES = (
    ("new_customer_info_ack_at", "customer_message_ack_at"),
    ("new_customer_info_external_ack_at", "customer_message_external_ack_at"),
)


def migrate(cr, version):
    for old, new in RENAMES:
        if _has_column(cr, old) and not _has_column(cr, new):
            cr.execute(
                'ALTER TABLE maintenance_request RENAME COLUMN "%s" TO "%s"'
                % (old, new)
            )
            _logger.info(
                "MIM-1960: renamed maintenance_request.%s -> %s", old, new
            )
        else:
            _logger.info(
                "MIM-1960: skipping rename %s -> %s (nothing to do)", old, new
            )


def _has_column(cr, name):
    cr.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'maintenance_request'
          AND column_name = %s
        """,
        (name,),
    )
    return bool(cr.fetchone())
