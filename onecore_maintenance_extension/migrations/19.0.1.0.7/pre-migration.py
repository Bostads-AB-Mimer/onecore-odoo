"""MIM-1960 — merge the per-audience ack columns into the shared one.

19.0.1.0.6 kept two ack columns, `customer_message_ack_at` (Mimer) and
`customer_message_external_ack_at` (external contractors), and baselined both
to the same verdict. The model change that landed on top of that (commit
906947c) collapsed acknowledgement into ONE shared column: whichever audience
acknowledges first now silences the status for everyone, so a second column
has nothing left to record.

Odoo runs every applicable version's pre-migration for every module, THEN
init_models() (which creates any new column the CURRENT field definitions
declare), THEN every applicable post-migration, in version order
(odoo/modules/loading.py:174 pre -> :194 init_models -> :230 post). That
ordering decides which of the two reachable database states this script
actually has work to do on:

  - Production, upgrading straight from 19.0.1.0.4: none of
    customer_message_ack_at, customer_message_external_ack_at,
    customer_message_unread_internal or customer_message_unread_external
    exist yet when this pre-migration runs — init_models() has not run, and
    19.0.1.0.6's post-migration (which creates the baselined
    customer_message_ack_at values) has not run either. Every column_exists()
    guard below is False, so this script is a complete no-op there, and
    19.0.1.0.6's post-migration goes on to baseline customer_message_ack_at
    from scratch under the merged, single-column shape init_models() is
    about to create.
  - A test/dev database already sitting on 19.0.1.0.6: it carries real
    acknowledgements made by testers under the old per-audience split — in
    both customer_message_ack_at and customer_message_external_ack_at, and
    the two now-orphaned sort booleans. This is the one place this script
    does real work: merge, then drop.

customer_message_ack_at is a WATERMARK, not a record of who clicked first:
_compute_customer_message_unread (models/maintenance.py) reads it as
`unread = last_customer_message_at > ack`, i.e. "everything dated at or
before ack has been seen". Under the new shared semantics, one audience's
acknowledgement counts for both, so merging the two per-audience watermarks
must keep the FURTHEST ADVANCED one, not the earliest. Four NULL
combinations, one expression:

    GREATEST(COALESCE(ack, ext), COALESCE(ext, ack))

    both NULL      -> GREATEST(NULL, NULL)  = NULL   (still outstanding)
    ack only       -> GREATEST(ack, ack)    = ack
    ext only       -> GREATEST(ext, ext)    = ext
    both non-null  -> GREATEST(ack, ext)    = the later of the two

Taking the earliest instead would be actively wrong on a database already at
19.0.1.0.6: a contractor acknowledges at t1, a new tenant message arrives at
t2, Mimer acknowledges at t3. LEAST(t3, t1) = t1, so t2 > t1 and the row
resurfaces as unread — and the next acknowledgement posts a second receipt
for a message that was already receipted. GREATEST(t3, t1) = t3 gives
t2 > t3 false, correctly silent.

This MUST be a pre-migration, not a post-migration:

  - The merge has to land in customer_message_ack_at before init_models()
    computes the new stored customer_message_unread column, so that
    computation reads the merged verdict rather than a stale one.
  - The drops must happen before init_models() re-validates the schema
    against the current field set, which no longer declares any of these
    three columns — the ORM is only guaranteed to tolerate their presence
    (as untracked raw columns) up to that point, not after.

Idempotent and side-effect free once applied: every step is guarded on
column_exists(), following the precedent in
migrations/19.0.1.0.6/pre-migration.py:57,72. After the external ack column
and the two orphan sort columns are gone, every guard is False and a second
run touches nothing.
"""

import logging

from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"
ACK_COLUMN = "customer_message_ack_at"
EXTERNAL_ACK_COLUMN = "customer_message_external_ack_at"
ORPHAN_SORT_COLUMNS = (
    "customer_message_unread_internal",
    "customer_message_unread_external",
)


def migrate(cr, version):
    _merge_external_ack(cr)
    _drop_orphan_sort_columns(cr)


def _merge_external_ack(cr):
    """Fold customer_message_external_ack_at into customer_message_ack_at,
    keeping the furthest-advanced (latest) non-null watermark, then drop the
    now-redundant column.

    Guarded on the external column existing at all — absent on a production
    upgrade from 1.0.4, since neither column has been created yet at this
    point in the migration ordering (see module docstring).
    """
    if not column_exists(cr, TABLE, EXTERNAL_ACK_COLUMN):
        _logger.info(
            "MIM-1960: %s.%s does not exist — nothing to merge.",
            TABLE,
            EXTERNAL_ACK_COLUMN,
        )
        return

    cr.execute("""
        UPDATE maintenance_request
        SET customer_message_ack_at = GREATEST(
                COALESCE(customer_message_ack_at, customer_message_external_ack_at),
                COALESCE(customer_message_external_ack_at, customer_message_ack_at))
        WHERE customer_message_ack_at IS NOT NULL
           OR customer_message_external_ack_at IS NOT NULL
        """)
    _logger.info(
        "MIM-1960: merged %d row(s) of %s.%s into %s (furthest-advanced watermark wins).",
        cr.rowcount,
        TABLE,
        EXTERNAL_ACK_COLUMN,
        ACK_COLUMN,
    )

    cr.execute(f'ALTER TABLE {TABLE} DROP COLUMN "{EXTERNAL_ACK_COLUMN}"')
    _logger.info("MIM-1960: dropped %s.%s", TABLE, EXTERNAL_ACK_COLUMN)


def _drop_orphan_sort_columns(cr):
    """Drop the two per-audience sort booleans MIM-1960 replaced with the
    single stored customer_message_unread.

    Each column is guarded independently — a database could in principle
    have one but not the other, and dropping is idempotent either way.
    """
    for column in ORPHAN_SORT_COLUMNS:
        if not column_exists(cr, TABLE, column):
            _logger.info(
                "MIM-1960: %s.%s does not exist — nothing to drop.", TABLE, column
            )
            continue
        cr.execute(f'ALTER TABLE {TABLE} DROP COLUMN "{column}"')
        _logger.info("MIM-1960: dropped %s.%s", TABLE, column)
