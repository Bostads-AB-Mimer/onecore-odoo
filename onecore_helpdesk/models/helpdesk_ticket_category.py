from odoo import api, fields, models


class HelpdeskTicketCategory(models.Model):
    _inherit = "helpdesk.ticket.category"

    form_ids = fields.One2many(
        comodel_name="helpdesk.ticket.form",
        inverse_name="category_id",
        string="Formulär",
        domain=[("kind", "=", "form")],
    )
    form_count = fields.Integer(compute="_compute_form_count")
    # Questions asked on every ticket in the category, whichever form it
    # uses (e.g. "Påverkan" for IT faults). Several categories may share one
    # add-on. See helpdesk.ticket.addon_properties.
    addon_form_id = fields.Many2one(
        comodel_name="helpdesk.ticket.form",
        string="Tilläggsformulär",
        domain=[("kind", "=", "addon")],
        ondelete="restrict",
        help="Frågor som ställs på alla ärenden i kategorin, under formulärets "
        "egna frågor.",
    )

    @api.depends("form_ids")
    def _compute_form_count(self):
        for category in self:
            category.form_count = len(category.form_ids)

    def write(self, vals):
        if "addon_form_id" not in vals:
            return super().write(vals)
        # Re-pointing the add-on recomputes the add-on block on every ticket
        # of the category without going through the ticket's write, so the
        # old answers would vanish without a trace. Keep them, as the
        # ticket's write does when its form or category changes.
        tickets = (
            self.env["helpdesk.ticket"]
            .sudo()
            .with_context(active_test=False)
            .search([("category_id", "in", self.ids)])
        )
        snapshots = tickets._answer_snapshots()
        res = super().write(vals)
        for ticket in tickets:
            old_addon, answers = snapshots[ticket.id]["addon_properties"]
            if old_addon and answers and ticket.addon_form_id != old_addon:
                ticket._log_answer_snapshot(old_addon, answers)
        return res
