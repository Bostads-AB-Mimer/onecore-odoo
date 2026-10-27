from odoo import api, fields, models


class HelpdeskTicketForm(models.Model):
    """A predefined intake form under a ticket category.

    The form carries the extra questions as an Odoo Properties definition.
    A ticket points at one form and its ``properties`` field reads this
    definition. Title and description stay the free text on every ticket;
    a form only adds questions on top, so a form with an empty definition
    is just "title + description".
    """

    _name = "helpdesk.ticket.form"
    _description = "Formulär för helpdesk-ärende"
    _order = "category_id, sequence, id"

    name = fields.Char(string="Namn", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category_id = fields.Many2one(
        comodel_name="helpdesk.ticket.category",
        string="Kategori",
        required=True,
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Företag",
        default=lambda self: self.env.company,
    )
    description = fields.Html(
        string="Introduktionstext",
        sanitize_style=True,
        help="Visas för den som fyller i formuläret, ovanför frågorna.",
    )
    show_in_portal = fields.Boolean(string="Visa i portalen", default=True)
    ticket_properties = fields.PropertiesDefinition(string="Frågor")
    question_summary = fields.Char(
        string="Frågor", compute="_compute_question_summary"
    )
    ticket_count = fields.Integer(compute="_compute_ticket_count")

    @api.depends("ticket_properties")
    def _compute_question_summary(self):
        for form in self:
            labels = [
                (prop.get("string") or prop.get("name"))
                + (" *" if prop.get("required") else "")
                for prop in form.ticket_properties or []
                if prop.get("type") != "separator"
            ]
            # labels may themselves contain commas ("Om program, vilket?")
            form.question_summary = " · ".join(labels)

    def action_view_tickets(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "helpdesk_mgmt.helpdesk_ticket_action"
        )
        action["domain"] = [("form_id", "=", self.id)]
        action["context"] = {
            "default_category_id": self.category_id.id,
            "default_form_id": self.id,
        }
        return action

    def _compute_ticket_count(self):
        counts = {
            form.id: count
            for form, count in self.env["helpdesk.ticket"]._read_group(
                [("form_id", "in", self.ids)], ["form_id"], ["__count"]
            )
        }
        for form in self:
            form.ticket_count = counts.get(form.id, 0)
