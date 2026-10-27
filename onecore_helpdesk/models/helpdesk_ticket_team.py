from odoo import fields, models


class HelpdeskTicketTeam(models.Model):
    _inherit = "helpdesk.ticket.team"

    default_category_id = fields.Many2one(
        comodel_name="helpdesk.ticket.category",
        string="Kategori för e-postärenden",
        domain="[('id', 'in', category_ids)]",
        help="Ärenden som kommer in via teamets e-postalias får denna kategori. "
        "Välj en kategori utan formulär, e-postärenden är fritext.",
    )
