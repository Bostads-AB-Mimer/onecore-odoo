from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# The two question blocks on a ticket: (answers field, container field). The
# form carries the questions of one errand type, the add-on form the
# questions common to every ticket of the category (e.g. "Påverkan").
QUESTION_BLOCKS = (
    ("properties", "form_id"),
    ("addon_properties", "addon_form_id"),
)


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
        domain="[('kind', '=', 'form'), ('category_id', '=', category_id)]",
        help="Vilket formulär ärendet anmäldes med. Styr vilka extra frågor "
        "som visas på ärendet.",
    )
    category_form_count = fields.Integer(related="category_id.form_count")
    # OCA points the definition at the team. Mimer has one IT team and several
    # forms per category, so the form is the container of the questions.
    properties = fields.Properties(
        definition="form_id.ticket_properties", copy=True, precompute=False
    )
    # A Properties definition may only follow one relation, so the category's
    # add-on is mirrored on the ticket for the second block to read.
    addon_form_id = fields.Many2one(
        related="category_id.addon_form_id",
        string="Tilläggsformulär",
        store=True,
        precompute=True,
    )
    addon_properties = fields.Properties(
        string="Tilläggsfrågor",
        definition="addon_form_id.ticket_properties",
        copy=True,
        precompute=False,
    )
    # titles and intros of the two blocks, for the ticket form view
    form_question_title = fields.Char(related="form_id.name")
    form_question_intro = fields.Html(related="form_id.description")
    addon_question_title = fields.Char(related="addon_form_id.name")
    addon_question_intro = fields.Html(related="addon_form_id.description")

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

    # Every ticket needs a category, and a form when the category has any,
    # whoever creates it: users in Odoo, the portal, the mail gateway, API
    # clients and automations alike. Automated callers get defaults instead
    # of an exemption: a ticket created without a category gets the team's
    # default category (see create). Only ``skip_ticket_form_rules`` in the
    # context bypasses the rule; message_new sets it, since an email can
    # neither pick a form nor answer questions. Not a constraint: write only
    # checks when the category, form or answers change, so stage moves and
    # other edits never trip over an old ticket.
    def _check_category_and_form_required(self, check_answers=True):
        if self.env.context.get("skip_ticket_form_rules"):
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
        if check_answers:
            self._check_required_answers()

    # Questions flagged ``required`` must be answered, in both blocks. The
    # flag is a Mimer extension of the definition schema (see models/base.py);
    # the widget enforces it in the browser, this is the server-side half.
    def _check_required_answers(self):
        fields_to_read = [field_name for field_name, _container in QUESTION_BLOCKS]
        for data in self.read(fields_to_read):
            missing = [
                prop.get("string") or prop["name"]
                for field_name in fields_to_read
                for prop in data[field_name]
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
        return self._is_blank_answer(prop.get("value"))

    @api.model
    def _is_blank_answer(self, value):
        """Unanswered in read format. Identity checks on purpose: ``0 == False``
        in Python, and a numeric answer of 0 is an answer."""
        return value is None or value is False or value in ("", [])

    # The form determines the category, so a payload with only form_id (an API
    # client, or an agent attaching a form to a ticket without one) implies it.
    # A payload without any category (mail gateway, automations, scripts) gets
    # the team's default category. An explicit empty category is kept and left
    # to the rule. A mismatching form is left to the constraint.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("form_id") and not vals.get("category_id"):
                vals["category_id"] = self._form_category_id(vals["form_id"])
            elif "category_id" not in vals:
                vals["category_id"] = self._default_category_id(vals)
        tickets = super().create(vals_list)
        tickets._check_category_and_form_required()
        return tickets

    @api.model
    def _default_category_id(self, vals):
        team = self.env["helpdesk.ticket.team"].browse(vals.get("team_id") or [])
        return team.default_category_id.id

    @api.model
    def _edits_definition(self, vals):
        """True when a question block in ``vals`` carries a definition change
        (the gear editor, read format) rather than plain answers."""
        for field_name, _container in QUESTION_BLOCKS:
            value = vals.get(field_name)
            if isinstance(value, list) and any(
                isinstance(prop, dict) and prop.get("definition_changed")
                for prop in value
            ):
                return True
        return False

    def write(self, vals):
        if vals.get("form_id") and "category_id" not in vals:
            without_category = self.filtered(lambda t: not t.category_id)
            if without_category:
                without_category.write(
                    dict(vals, category_id=self._form_category_id(vals["form_id"]))
                )
                rest = self - without_category
                return rest.write(vals) if rest else True
        touches_container = "category_id" in vals or "form_id" in vals
        touches_answers = any(field_name in vals for field_name, _c in QUESTION_BLOCKS)
        snapshots = self._answer_snapshots() if touches_container else {}
        res = super().write(vals)
        if touches_container or touches_answers:
            # Editing the questions with the gear icon writes the new
            # definition through the host ticket. That is configuration, not
            # answering: a required question added that way is enforced from
            # the next answer edit on, not on the ticket it was added from.
            self._check_category_and_form_required(
                check_answers=not self._edits_definition(vals)
            )
        for ticket in self:
            for field_name, container in QUESTION_BLOCKS:
                old_form, answers = snapshots.get(ticket.id, {}).get(
                    field_name, (False, [])
                )
                if old_form and answers and ticket[container] != old_form:
                    ticket._log_answer_snapshot(old_form, answers)
        return res

    @api.model
    def _form_category_id(self, form_id):
        return self.env["helpdesk.ticket.form"].browse(form_id).category_id.id

    def onchange(self, values, field_names, fields_spec):
        result = super().onchange(values, field_names, fields_spec)
        for field_name, container in QUESTION_BLOCKS:
            self._onchange_return_questions(
                field_name, container, values, field_names, fields_spec, result
            )
        return result

    def _onchange_return_questions(
        self, field_name, container, values, field_names, fields_spec, result
    ):
        """Send a block's questions to the client as soon as its container
        (form or add-on form) changes.

        Odoo only returns a field from an onchange when its value changed
        between the before and after snapshots. Unanswered properties are not
        stored, so with questions that have no defaults the stored answers are
        ``{}`` both before and after, the block is left out of the response,
        and the questions only appear once the ticket is saved and read back.
        Odoo's own tests for this flow all use defaults. The same gap leaves
        stale questions on screen when the container is cleared.
        """
        if field_name not in fields_spec:
            return
        value = result.setdefault("value", {})
        if field_name in value:
            return
        if container in value:
            new_container = value[container]
            container_id = (
                new_container["id"] if isinstance(new_container, dict) else new_container
            )
        elif container in field_names:
            container_id = values.get(container)
        else:
            return
        if not container_id:
            value[field_name] = []
            return
        field = self._fields[field_name]
        # keep the answers the client already has (same keys survive a switch),
        # then apply the new container's defaults, exactly as the compute would
        ticket = self.new({container: container_id, field_name: values.get(field_name) or []})
        ticket[field_name] = field._add_default_values(
            self.env, {field_name: ticket[field_name], container: ticket[container]}
        )
        value[field_name] = ticket.web_read({field_name: {}})[0][field_name]

    @api.model
    def message_new(self, msg, custom_values=None):
        """Email tickets are free text: create gives them the team's default
        category, and an email can neither pick a form nor answer questions,
        so the rules are skipped and an agent completes the ticket later."""
        return super(
            HelpdeskTicket, self.with_context(skip_ticket_form_rules=True)
        ).message_new(msg, custom_values=custom_values)

    # Odoo recomputes a question block when its container changes and keeps
    # only the answers whose keys exist in the new definition (none, when the
    # container is cleared). Property changes are not tracked, so keep the old
    # answers readable in the chatter.
    def _answer_snapshots(self):
        """{ticket id: {answers field: (form record, [(label, display)])}}.

        One batched read: the read format carries the definition (labels,
        selection options, tags) and display names for relational values.
        """
        fields_to_read = [field_name for field_name, _container in QUESTION_BLOCKS]
        by_id = {ticket.id: ticket for ticket in self}
        snapshots = {}
        for data in self.read(fields_to_read):
            ticket = by_id[data["id"]]
            snapshots[ticket.id] = {
                field_name: (
                    ticket[container],
                    [a for a in map(self._format_answer, data[field_name]) if a],
                )
                for field_name, container in QUESTION_BLOCKS
            }
        return snapshots

    def _displayed_answers(self):
        """[(label, display value)] of the answered questions, form block
        first, then the add-on block, for the portal ticket page."""
        self.ensure_one()
        snapshot = self._answer_snapshots().get(self.id, {})
        return [
            answer
            for field_name, _container in QUESTION_BLOCKS
            for answer in snapshot.get(field_name, (False, []))[1]
        ]

    @api.model
    def _format_answer(self, prop):
        """(label, display) for an answered property in read format, else None."""
        value = prop.get("value")
        ptype = prop.get("type")
        if ptype == "separator" or self._is_blank_answer(value):
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
