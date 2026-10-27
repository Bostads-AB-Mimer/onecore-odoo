from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    form_id = fields.Many2one(
        comodel_name="helpdesk.ticket.form",
        string="Formulär",
        compute="_compute_form_id",
        store=True,
        readonly=False,
        precompute=True,
        ondelete="restrict",
        tracking=True,
        domain="[('category_id', '=', category_id)]",
        help="Vilket formulär ärendet anmäldes med. Styr vilka extra frågor "
        "som visas på ärendet.",
    )
    category_form_count = fields.Integer(related="category_id.form_count")
    # OCA points the definition at the team. Mimer has one IT team and several
    # forms per category, so the form is the container of the questions.
    properties = fields.Properties(
        definition="form_id.ticket_properties", copy=True, precompute=False
    )

    @api.depends("category_id")
    def _compute_form_id(self):
        """Keep a form that matches the category, preselect the category's
        only form, otherwise clear."""
        for ticket in self:
            forms = ticket.category_id.form_ids
            if ticket.form_id and ticket.form_id in forms:
                continue
            ticket.form_id = forms if len(forms) == 1 else False

    @api.constrains("form_id", "category_id")
    def _check_form_matches_category(self):
        for ticket in self:
            if ticket.form_id and ticket.form_id.category_id != ticket.category_id:
                raise ValidationError(
                    _(
                        "Formuläret %(form)s hör till kategorin %(form_category)s, "
                        "inte %(category)s.",
                        form=ticket.form_id.name,
                        form_category=ticket.form_id.category_id.complete_name,
                        category=ticket.category_id.complete_name or _("(ingen)"),
                    )
                )

    # Every ticket made by a user in Odoo needs a category, and a form when the
    # category has any. Not a constraint: the mail gateway and the OCA portal
    # create as superuser and are exempt (email gets the team's default
    # category instead, see message_new).
    def _check_category_and_form_required(self):
        if self.env.su:
            return
        for ticket in self:
            if not ticket.category_id:
                raise ValidationError(_("Välj en kategori för ärendet."))
            if ticket.category_id.form_ids and not ticket.form_id:
                raise ValidationError(
                    _(
                        "Kategorin %(category)s kräver att du väljer ett formulär.",
                        category=ticket.category_id.complete_name,
                    )
                )
        self._check_required_answers()

    # Questions flagged ``required`` on the form must be answered. The flag is
    # a Mimer extension of the definition schema (see models/base.py); the
    # widget enforces it in the browser, this is the server-side half.
    def _check_required_answers(self):
        with_form = self.filtered("form_id")
        if not with_form:
            return
        for data in with_form.read(["properties"]):
            missing = [
                prop.get("string") or prop["name"]
                for prop in data["properties"]
                if self._is_missing_required_answer(prop)
            ]
            if missing:
                raise ValidationError(
                    _(
                        "Besvara de obligatoriska frågorna: %(questions)s.",
                        questions=", ".join(missing),
                    )
                )

    @api.model
    def _is_missing_required_answer(self, prop):
        if not prop.get("required") or prop.get("type") in ("separator", "boolean"):
            return False
        value = prop.get("value")
        # identity checks: 0 is an answer
        return value is None or value is False or value in ("", [])

    # The form determines the category, so a payload with only form_id (an API
    # client, or an agent attaching a form to a ticket without one) implies it.
    # A ticket that already has a category keeps it, and a mismatching form is
    # left to the constraint.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("form_id") and not vals.get("category_id"):
                vals["category_id"] = self._form_category_id(vals["form_id"])
        tickets = super().create(vals_list)
        tickets._check_category_and_form_required()
        return tickets

    def write(self, vals):
        if vals.get("form_id") and "category_id" not in vals:
            without_category = self.filtered(lambda t: not t.category_id)
            if without_category:
                without_category.write(
                    dict(vals, category_id=self._form_category_id(vals["form_id"]))
                )
                rest = self - without_category
                return rest.write(vals) if rest else True
        touches_form = "category_id" in vals or "form_id" in vals
        snapshots = self._answer_snapshots() if touches_form else {}
        res = super().write(vals)
        if touches_form or "properties" in vals:
            self._check_category_and_form_required()
        for ticket in self:
            old_form, answers = snapshots.get(ticket.id, (False, []))
            if old_form and answers and ticket.form_id != old_form:
                ticket._log_answer_snapshot(old_form, answers)
        return res

    @api.model
    def _form_category_id(self, form_id):
        return self.env["helpdesk.ticket.form"].browse(form_id).category_id.id

    def onchange(self, values, field_names, fields_spec):
        result = super().onchange(values, field_names, fields_spec)
        self._onchange_return_questions(values, field_names, fields_spec, result)
        return result

    def _onchange_return_questions(self, values, field_names, fields_spec, result):
        """Send the form's questions to the client as soon as the form changes.

        Odoo only returns a field from an onchange when its value changed
        between the before and after snapshots. Unanswered properties are not
        stored, so with a form whose questions have no defaults the stored
        answers are ``{}`` both before and after, ``properties`` is left out
        of the response, and the questions only appear once the ticket is
        saved and read back. Odoo's own tests for this flow all use defaults.
        The same gap leaves stale questions on screen when the form is cleared.
        """
        if "properties" not in fields_spec:
            return
        value = result.setdefault("value", {})
        if "properties" in value:
            return
        if "form_id" in value:
            form = value["form_id"]
            form_id = form["id"] if isinstance(form, dict) else form
        elif "form_id" in field_names:
            form_id = values.get("form_id")
        else:
            return
        if not form_id:
            value["properties"] = []
            return
        field = self._fields["properties"]
        # keep the answers the client already has (same keys survive a switch),
        # then apply the new form's defaults, exactly as the compute would
        ticket = self.new({"form_id": form_id, "properties": values.get("properties") or []})
        ticket.properties = field._add_default_values(
            self.env, {"properties": ticket.properties, "form_id": ticket.form_id}
        )
        value["properties"] = ticket.web_read({"properties": {}})[0]["properties"]

    @api.model
    def message_new(self, msg, custom_values=None):
        """Email tickets are free text: give them the team's default category
        so the category rule holds without attaching a form."""
        custom_values = dict(custom_values or {})
        if not custom_values.get("category_id") and custom_values.get("team_id"):
            team = self.env["helpdesk.ticket.team"].browse(custom_values["team_id"])
            if team.default_category_id:
                custom_values["category_id"] = team.default_category_id.id
        return super().message_new(msg, custom_values=custom_values)

    # Odoo recomputes ``properties`` when the form changes and keeps only the
    # answers whose keys exist in the new definition (none, when the form is
    # cleared). Property changes are not tracked, so keep the old answers
    # readable in the chatter.
    def _answer_snapshots(self):
        """{ticket id: (form, [(label, display value)])} for tickets with a form.

        One batched read: the read format carries the definition (labels,
        selection options, tags) and display names for relational values.
        """
        with_form = self.filtered("form_id")
        if not with_form:
            return {}
        forms = {ticket.id: ticket.form_id for ticket in with_form}
        snapshots = {}
        for data in with_form.read(["properties"]):
            answers = [
                answer
                for answer in map(self._format_answer, data["properties"])
                if answer
            ]
            snapshots[data["id"]] = (forms[data["id"]], answers)
        return snapshots

    @api.model
    def _format_answer(self, prop):
        """(label, display) for an answered property in read format, else None.

        Identity checks on purpose: ``0 == False`` in Python, and a numeric
        answer of 0 is an answer.
        """
        value = prop.get("value")
        ptype = prop.get("type")
        if ptype == "separator" or value is None or value is False or value in ("", []):
            return None
        if ptype == "selection":
            display = dict(prop.get("selection") or []).get(value, value)
        elif ptype == "many2one":
            display = value[1] if isinstance(value, (list, tuple)) else value
        elif ptype == "many2many":
            display = ", ".join(str(item[1]) for item in value)
        elif ptype == "tags":
            labels = {tag[0]: tag[1] for tag in prop.get("tags") or []}
            display = ", ".join(str(labels.get(key, key)) for key in value)
        elif ptype == "boolean":
            display = _("Ja")
        else:
            display = value
        return prop.get("string") or prop["name"], display

    def _log_answer_snapshot(self, old_form, answers):
        self.ensure_one()
        items = Markup("").join(
            Markup("<li>%s: %s</li>") % (escape(label), escape(str(value)))
            for label, value in answers
        )
        body = Markup("<p>%s</p><ul>%s</ul>") % (
            _("Svar från formuläret %(form)s innan det byttes:", form=old_form.name),
            items,
        )
        self.message_post(body=body, subtype_xmlid="mail.mt_note")
