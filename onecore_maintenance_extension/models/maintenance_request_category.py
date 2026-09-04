from odoo import models, fields


class OnecoreMaintenanceRequestCategory(models.Model):
    _name = "maintenance.request.category"
    _description = "Maintenance Request Category"

    name = fields.Char("Namn", required=True)
    active = fields.Boolean(default=True)
    color = fields.Integer("Färg", default=0)

    # MIM-1970: lets OrderingTeamService break ties for someone who belongs
    # to several teams (Kundcenter's two queues), without matching on this
    # category's (translatable, renameable) name. Only teams the orderer
    # actually belongs to ever win — see
    # OrderingTeamService._preferred_category_team for why.
    preferred_ordering_team_id = fields.Many2one(
        "maintenance.team",
        string="Föredragen beställande resursgrupp",
        help=(
            "Om satt: en beställare som själv är medlem i den här "
            "resursgruppen får den som Beställande resursgrupp på ärenden "
            "med den här kategorin, i stället för sin första resursgrupp. "
            "Beställare som inte är medlemmar i gruppen påverkas inte. "
            "Lämna tomt om kategorin inte behöver särskiljas så här."
        ),
    )
