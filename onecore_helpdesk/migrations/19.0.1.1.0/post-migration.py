"""Set the IT team's default category on databases that installed the team
before the field existed.

``default_category_id`` was added to the ``team_it`` record in
data/helpdesk_it_team_data.xml, which is loaded with noupdate="1" so that
changes IT makes in the UI survive upgrades. A noupdate record is not
rewritten on upgrade, so existing databases never receive the new field value
from the XML. Without it, tickets created by email get no category, and since
the ticket form view requires a category, agents cannot save them.

Only fills the field when it is empty: a value set in the UI is kept.
"""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    team = env.ref("onecore_helpdesk.team_it", raise_if_not_found=False)
    category = env.ref("onecore_helpdesk.category_it_other", raise_if_not_found=False)
    if team and category and not team.default_category_id:
        team.default_category_id = category
