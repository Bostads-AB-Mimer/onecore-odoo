from odoo import api, fields, models


class HelpdeskTicketCategory(models.Model):
    _inherit = "helpdesk.ticket.category"

    form_ids = fields.One2many(
        comodel_name="helpdesk.ticket.form",
        inverse_name="category_id",
        string="Formulär",
    )
    form_count = fields.Integer(compute="_compute_form_count")

    @api.depends("form_ids")
    def _compute_form_count(self):
        for category in self:
            category.form_count = len(category.form_ids)
