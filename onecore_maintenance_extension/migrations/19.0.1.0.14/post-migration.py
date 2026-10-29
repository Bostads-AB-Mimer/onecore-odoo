"""Label owner_user_id "Beställare" in every installed language, and give the
shipped favorites the names and grouping the business settled on.

The field's string changed in code, which only replaces the en_US label: the
upgrade keeps stock maintenance's Swedish "Skapad av användare". Fresh
installs get the same from the post_init hook.

The favorites are noupdate data, so the upgrade leaves existing ones as they
are; the values below match data/ir_filters.xml. The new "Mina beställningar"
favorite is created by the data file itself.
"""
from odoo import SUPERUSER_ID, api

FAVORITES = {
    "filter_my_kvv_areas": {"name": "Mina inkomna ärenden"},
    "filter_ordered_by_my_department_at_others": {
        "name": "Beställt av min enhet hos andra – alla",
    },
    "filter_my_active_orders_by_team": {
        "name": "Beställt av min enhet hos andra – aktiva",
        "context": "{'group_by': ['stage_id']}",
    },
    "filter_in_my_district_ordered_by_others": {
        "name": "Beställt av andra på min enhet",
    },
}


def migrate(cr, version):
    from odoo.addons.onecore_maintenance_extension.hooks import _label_owner_as_orderer

    env = api.Environment(cr, SUPERUSER_ID, {})
    _label_owner_as_orderer(env)
    for xml_name, vals in FAVORITES.items():
        favorite = env.ref(
            f"onecore_maintenance_extension.{xml_name}", raise_if_not_found=False
        )
        if favorite:
            favorite.write(vals)
