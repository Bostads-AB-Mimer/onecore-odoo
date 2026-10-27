from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def summarize_questions(definition):
    """One line of question labels for list views: separators skipped,
    required questions marked with " *". Joined with " · " because labels may
    themselves contain commas ("Om program, vilket?")."""
    return " · ".join(
        (prop.get("string") or prop.get("name")) + (" *" if prop.get("required") else "")
        for prop in definition or []
        if prop.get("type") != "separator"
    )


class HelpdeskTicketForm(models.Model):
    """A predefined set of questions, as an Odoo Properties definition.

    Two kinds share the model:

    - ``form``: the intake form of one errand type, under a category. The
      requester picks one; the ticket's ``properties`` read its definition.
    - ``addon``: questions common to every ticket of a category (e.g.
      "Påverkan" for IT faults). A category points at one add-on, several
      categories may share it; the ticket's ``addon_properties`` read it.

    Title and description stay the free text on every ticket; a form with an
    empty definition is just "title + description".
    """

    _name = "helpdesk.ticket.form"
    _description = "Formulär för helpdesk-ärende"
    _order = "category_id, sequence, id"

    name = fields.Char(string="Namn", required=True, translate=True)
    kind = fields.Selection(
        selection=[("form", "Formulär"), ("addon", "Tilläggsformulär")],
        string="Typ",
        default="form",
        required=True,
        help="Formulär: väljs av anmälaren, hör till en kategori. "
        "Tilläggsformulär: frågor som ställs på alla ärenden i de kategorier "
        "som pekar på det, under formulärets egna frågor.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category_id = fields.Many2one(
        comodel_name="helpdesk.ticket.category",
        string="Kategori",
        ondelete="restrict",
        index=True,
    )
    addon_category_ids = fields.One2many(
        comodel_name="helpdesk.ticket.category",
        inverse_name="addon_form_id",
        string="Används av kategorier",
    )
    # the add-on asked together with this form, via its category
    category_addon_form_id = fields.Many2one(
        related="category_id.addon_form_id", string="Tilläggsformulär"
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Företag",
        default=lambda self: self.env.company,
    )
    description = fields.Html(
        string="Introduktionstext",
        sanitize_style=True,
        help="Visas under rubriken, ovanför frågorna, för den som fyller i dem.",
    )
    show_in_portal = fields.Boolean(
        string="Visa i portalen",
        default=True,
        help="Gäller formulär. Ett tilläggsformulär följer sin kategori.",
    )
    ticket_properties = fields.PropertiesDefinition(string="Frågor")
    question_summary = fields.Char(
        string="Frågor", compute="_compute_question_summary"
    )
    ticket_count = fields.Integer(compute="_compute_ticket_count")

    @api.constrains("kind", "category_id")
    def _check_kind_matches_category(self):
        for form in self:
            if form.kind == "form" and not form.category_id:
                raise ValidationError(
                    _("Formuläret %(form)s måste höra till en kategori.", form=form.name)
                )
            if form.kind == "addon" and form.category_id:
                raise ValidationError(
                    _(
                        "Tilläggsformuläret %(form)s hör inte till en kategori; "
                        "kategorier pekar på det i stället.",
                        form=form.name,
                    )
                )

    @api.depends("ticket_properties")
    def _compute_question_summary(self):
        for form in self:
            form.question_summary = summarize_questions(form.ticket_properties)

    def _ticket_field(self):
        """The ticket field that points at forms of this kind."""
        self.ensure_one()
        return "form_id" if self.kind == "form" else "addon_form_id"

    def action_view_tickets(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "helpdesk_mgmt.helpdesk_ticket_action"
        )
        action["domain"] = [(self._ticket_field(), "=", self.id)]
        if self.kind == "form":
            action["context"] = {
                "default_category_id": self.category_id.id,
                "default_form_id": self.id,
            }
        return action

    def _compute_ticket_count(self):
        Ticket = self.env["helpdesk.ticket"]
        counts = {}
        for ticket_field in ("form_id", "addon_form_id"):
            for form, count in Ticket._read_group(
                [(ticket_field, "in", self.ids)], [ticket_field], ["__count"]
            ):
                counts[(ticket_field, form.id)] = count
        for form in self:
            form.ticket_count = counts.get((form._ticket_field(), form.id), 0)
