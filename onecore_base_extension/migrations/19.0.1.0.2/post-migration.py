import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT lower(login), array_agg(id), count(*)
        FROM res_users
        GROUP BY 1
        HAVING count(*) > 1
    """)
    collisions = cr.fetchall()
    if collisions:
        _logger.warning(
            "Skipping login lowercase normalisation - %s collision(s) found: %s. "
            "Resolve duplicates manually then re-run -u onecore_base_extension.",
            len(collisions), collisions,
        )
        return

    cr.execute("""
        UPDATE res_users SET login = lower(login)
        WHERE login <> lower(login)
    """)
    _logger.info("Lowercased %s res_users.login row(s)", cr.rowcount)
