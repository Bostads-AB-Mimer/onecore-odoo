from odoo import models, fields


class OnecoreMaintenanceRequestCategory(models.Model):
    _name = "maintenance.request.category"
    _description = "Maintenance Request Category"

    name = fields.Char("Namn", required=True)
    active = fields.Boolean(default=True)
    color = fields.Integer("Färg", default=0)
    # Read by OrderingDepartmentService when a member of Kundcenter creates
    # an ärende in the category.
    kundcenter_orders = fields.Boolean(
        "Kundcenter beställer",
        help="Ärenden som Kundcenter skapar i kategorin räknas som Kundcenters "
        "beställningar, t.ex. nycklar. I andra kategorier förmedlar Kundcenter "
        "bara ärendet och står inte som beställande enhet.",
    )
