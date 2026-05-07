"""Migration for MIM-1768 — auto-follower bug after Odoo 19 upgrade.

Odoo 19 commit 78168325708 changed mail.message.subtype._get_auto_subscription_subtypes
to read `relation_field` even on same-model subtypes (in Odoo 17 an `elif` short-circuited
this branch). The Mimer subtype `mt_from_tenant` had `relation_field='user_id'` set,
which was harmless in Odoo 17 but in Odoo 19 causes `_message_auto_subscribe` to treat
each `user_id` value as if it were a `maintenance.request.id` and copy the followers
of that arbitrary ticket onto every newly created ticket.

This migration:

1. Clears the `relation_field` column on the existing `mt_from_tenant` subtype row
   (the XML data file is loaded with noupdate="1" so removing the field there does
   not auto-clear an existing column value — we have to do it explicitly).
2. Removes the bogus `mail.followers` rows that the bug inserted between the upgrade
   and this fix. Scope:
     - Only `maintenance.request` rows created at-or-after the Odoo 19 deploy.
     - Keeps any follower whose partner has a *legitimate* connection to the ticket
       (creator, user_id, owner_user_id, current team member, message author or
       recipient, manually added via the UI audit log, or Mimer.nu).
3. Clears the registry cache so the next request re-reads the fixed subtype set.
"""
import json
import logging

# Odoo 19 deploy went live at this timestamp in production.
ODOO_19_DEPLOY_AT = '2026-05-04 10:23:21'

# Mimer.nu — the system/admin partner, intentionally kept as follower of all tickets.
MIMER_NU_PARTNER_ID = 3

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    _clear_relation_field(env)
    deleted = _cleanup_bogus_followers(env)
    env.registry.clear_cache()

    env.cr.commit()
    _logger.info(
        "MIM-1768 migration complete: cleared mt_from_tenant.relation_field, "
        "deleted %d bogus mail.followers rows.", deleted,
    )


def _clear_relation_field(env):
    """Drop the `relation_field` value from the mt_from_tenant subtype row."""
    subtype = env.ref(
        'onecore_maintenance_extension.mt_from_tenant',
        raise_if_not_found=False,
    )
    if subtype and subtype.relation_field:
        subtype.write({'relation_field': False})


def _cleanup_bogus_followers(env):
    """Delete `mail.followers` rows on post-upgrade maintenance.request records
    whose partner has no legitimate connection to the ticket.

    A partner is considered legitimately connected if any of these are true:
      - It is Mimer.nu (partner 3 — system actor, kept by request).
      - It is the partner of the ticket's create_uid / user_id / owner_user_id.
      - It is the partner of any current team member.
      - It is recorded in the mail.followers.edit UI audit log as a manual add
        for this ticket (someone clicked "Add follower" in the chatter).
      - It authored or was an explicit recipient (partner_ids) on any
        mail.message of this ticket (covers @mentions and direct sends).

    Returns the number of rows deleted.
    """
    requests = env['maintenance.request'].search([
        ('create_date', '>=', ODOO_19_DEPLOY_AT),
    ])
    if not requests:
        return 0

    request_ids = requests.ids

    # Pre-compute audit-log "this is legitimate" pairs once for all tickets.
    audit_pairs = _collect_manual_follower_adds(env, request_ids)
    message_pairs = _collect_message_partner_pairs(env, request_ids)

    deleted = 0
    for req in requests:
        legitimate_partners = (
            req.create_uid.partner_id
            | req.user_id.partner_id
            | req.owner_user_id.partner_id
            | req.maintenance_team_id.member_ids.partner_id
        )
        bad = req.message_follower_ids.filtered(
            lambda f: f.partner_id.id != MIMER_NU_PARTNER_ID
                      and f.partner_id not in legitimate_partners
                      and (f.partner_id.id, req.id) not in audit_pairs
                      and (f.partner_id.id, req.id) not in message_pairs
        )
        if bad:
            deleted += len(bad)
            bad.unlink()
    return deleted


def _collect_manual_follower_adds(env, ticket_ids):
    """Return {(partner_id, ticket_id)} pairs that were manually added via the
    "Add follower" UI (logged in mail.followers.edit since Odoo 19)."""
    pairs = set()
    if not ticket_ids:
        return pairs

    # Use raw SQL to avoid depending on the Odoo field name for the m2m.
    env.cr.execute("""
        SELECT mfe.id, mfe.res_ids
        FROM mail_followers_edit mfe
        WHERE mfe.res_model = 'maintenance.request'
          AND mfe.operation = 'add'
    """)
    edits = env.cr.fetchall()
    if not edits:
        return pairs

    edit_ids = [eid for eid, _ in edits]
    env.cr.execute("""
        SELECT mail_followers_edit_id, res_partner_id
        FROM mail_followers_edit_res_partner_rel
        WHERE mail_followers_edit_id = ANY(%s)
    """, (edit_ids,))
    partners_by_edit = {}
    for eid, pid in env.cr.fetchall():
        partners_by_edit.setdefault(eid, []).append(pid)

    ticket_id_set = set(ticket_ids)
    for eid, res_ids_str in edits:
        try:
            res_ids = json.loads(res_ids_str or '[]')
        except (json.JSONDecodeError, TypeError):
            continue
        relevant = [tid for tid in res_ids if tid in ticket_id_set]
        if not relevant:
            continue
        for tid in relevant:
            for pid in partners_by_edit.get(eid, ()):
                pairs.add((pid, tid))
    return pairs


def _collect_message_partner_pairs(env, ticket_ids):
    """Return {(partner_id, ticket_id)} pairs where the partner authored OR was
    an explicit recipient on a mail.message belonging to the ticket — i.e.,
    @mentions and message_post(partner_ids=[...]) calls."""
    if not ticket_ids:
        return set()

    pairs = set()

    # Authors
    env.cr.execute("""
        SELECT DISTINCT mm.author_id, mm.res_id
        FROM mail_message mm
        WHERE mm.model = 'maintenance.request'
          AND mm.res_id = ANY(%s)
          AND mm.author_id IS NOT NULL
    """, (ticket_ids,))
    pairs.update(env.cr.fetchall())

    # Explicit recipients (@mention / partner_ids on message_post)
    env.cr.execute("""
        SELECT DISTINCT rel.res_partner_id, mm.res_id
        FROM mail_message_res_partner_rel rel
        JOIN mail_message mm ON mm.id = rel.mail_message_id
        WHERE mm.model = 'maintenance.request'
          AND mm.res_id = ANY(%s)
    """, (ticket_ids,))
    pairs.update(env.cr.fetchall())

    return pairs
