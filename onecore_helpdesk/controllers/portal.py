from datetime import datetime

import pytz

from odoo import _
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.helpdesk_mgmt.controllers.main import HelpdeskTicketController

# Question types the portal renders as plain inputs. Relational types need
# record lookups the portal user cannot make, html needs an editor and
# monetary a currency: a form shown in the portal should not use them. They
# are skipped when rendering and parsing.
PORTAL_QUESTION_TYPES = (
    "char",
    "text",
    "integer",
    "float",
    "boolean",
    "date",
    "datetime",
    "selection",
    "tags",
    "separator",
)

# Input names in the portal form: question_<property name> for the form's
# questions, addon_question_<property name> for the category's add-on form.
QUESTION_PREFIX = "question_"
ADDON_QUESTION_PREFIX = "addon_question_"


class OnecoreHelpdeskTicketController(HelpdeskTicketController):
    """Portal ticket intake with the category's forms and their questions.

    The OCA page offers team, category, subject, attachments and
    description. This adds a form select and, per form, the questions from
    its definition, posts the answers as the ticket's ``properties`` and
    routes the ticket to the team that owns the category. The ticket rules
    of helpdesk.ticket (category required, form required when the category
    has forms, required answers) apply to the portal like to everyone else;
    a rejected submit shows the page again with the message and the entered
    values.
    """

    # The category rule is uniform (see helpdesk.ticket), so the portal
    # always offers the categories and requires one, whatever the OCA
    # company setting "Select category in Helpdesk portal" says.
    def _get_categories(self, **kw):
        return (
            request.env["helpdesk.ticket.category"]
            .with_company(request.env.company.id)
            .search([("active", "=", True), ("show_in_portal", "=", True)])
        )

    def _get_portal_forms(self, categories):
        # the portal record rule on the form already limits to show_in_portal,
        # the explicit domain keeps the intent visible
        return request.env["helpdesk.ticket.form"].search(
            [
                ("kind", "=", "form"),
                ("category_id", "in", categories.ids),
                ("show_in_portal", "=", True),
            ]
        )

    # An add-on form follows its category into the portal: it is read as
    # superuser and rendered whenever the category is, so its show_in_portal
    # flag and the portal record rule do not apply to it.
    def _get_category_addons(self, categories):
        addons = {}
        for category in categories:
            addon = category.sudo().addon_form_id
            if addon:
                addons[category.id] = addon
        return addons

    def _get_create_new_ticket_values(self, **kw):
        values = super()._get_create_new_ticket_values(**kw)
        values.update(
            {
                "ticket_category_id_required": True,
                "forms": self._get_portal_forms(values["categories"]),
                "question_prefix": QUESTION_PREFIX,
                "addon_question_prefix": ADDON_QUESTION_PREFIX,
                "category_addons": self._get_category_addons(values["categories"]),
                "portal_question_types": PORTAL_QUESTION_TYPES,
                # filled when the page is shown again after a rejected submit
                "error": False,
                "submitted": {},
                "submitted_lists": {},
            }
        )
        return values

    def submit_ticket(self, **kw):
        try:
            # the rules raise after the insert; roll it back and keep the
            # request alive to show the page again
            with request.env.cr.savepoint():
                return super().submit_ticket(**kw)
        except ValidationError as error:
            return self._render_rejected_ticket(error.args[0], **kw)

    def _render_rejected_ticket(self, message, **kw):
        values = self._get_create_new_ticket_values(**kw)
        posted = request.httprequest.form
        values.update(
            {
                "error": message,
                "submitted": kw,
                "submitted_lists": {
                    key: posted.getlist(key) for key in posted if key in kw
                },
            }
        )
        return request.render("helpdesk_mgmt.portal_create_ticket", values)

    def _prepare_submit_ticket_vals(self, **kw):
        vals = super()._prepare_submit_ticket_vals(**kw)
        category = request.env["helpdesk.ticket.category"].browse(
            vals.get("category_id") or []
        )
        form = self._get_submitted_form(category, kw.get("form"))
        vals["form_id"] = form.id
        if form:
            vals["properties"] = self._parse_question_answers(
                form.ticket_properties, kw, QUESTION_PREFIX
            )
        addon = category.sudo().addon_form_id
        if addon:
            vals["addon_properties"] = self._parse_question_answers(
                addon.ticket_properties, kw, ADDON_QUESTION_PREFIX
            )
        if not vals.get("team_id") and category:
            team = self._get_team_for_category(category)
            if team:
                vals["team_id"] = team.id
                vals["stage_id"] = team._get_applicable_stages()[:1].id
        return vals

    def _get_submitted_form(self, category, form_param):
        Form = request.env["helpdesk.ticket.form"]
        if not form_param or not category:
            # without a category the ticket rule reports the missing category
            return Form
        form_id = int(form_param) if str(form_param).isdigit() else 0
        form = Form.search(
            [
                ("id", "=", form_id),
                ("kind", "=", "form"),
                ("category_id", "=", category.id),
                ("show_in_portal", "=", True),
            ],
            limit=1,
        )
        if not form:
            raise ValidationError(
                _("Formuläret kan inte användas för den valda kategorin.")
            )
        return form

    # The OCA page only sets a team when the company lets the requester pick
    # one. Mimer routes by category instead: the team that owns the category
    # gets the ticket.
    def _get_team_for_category(self, category):
        return (
            request.env["helpdesk.ticket.team"]
            .sudo()
            .search([("category_ids", "in", category.id)], limit=1)
        )

    def _parse_question_answers(self, definition, kw, prefix):
        """{property name: value} for the answered questions of a definition
        (a form's or a category's), read from inputs named ``prefix + name``.

        Unanswered questions are left out, so the required-answer check on
        the ticket sees them as missing. Question types the portal does not
        render are left out too.
        """
        answers = {}
        posted = request.httprequest.form
        for question in definition:
            name = question["name"]
            key = prefix + name
            qtype = question.get("type")
            if qtype == "tags":
                value = self._parse_tags_answer(question, posted.getlist(key))
            elif qtype == "boolean":
                value = bool(kw.get(key))
            else:
                value = self._parse_question_answer(question, kw.get(key))
            if value is not None:
                answers[name] = value
        return answers

    def _parse_tags_answer(self, question, raw_values):
        allowed = {tag[0] for tag in question.get("tags") or []}
        values = [value for value in raw_values if value in allowed]
        return values or None

    def _parse_question_answer(self, question, raw):
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return None
        qtype = question.get("type")
        label = question.get("string") or question["name"]
        if qtype in ("char", "text"):
            return raw
        if qtype == "integer":
            try:
                return int(raw)
            except ValueError:
                raise ValidationError(
                    _("Svaret på %(question)s måste vara ett heltal.", question=label)
                ) from None
        if qtype == "float":
            try:
                return float(raw.replace(",", "."))
            except ValueError:
                raise ValidationError(
                    _("Svaret på %(question)s måste vara ett tal.", question=label)
                ) from None
        if qtype == "date":
            return self._parse_date_answer(raw, label)
        if qtype == "datetime":
            return self._parse_datetime_answer(raw, label)
        if qtype == "selection":
            options = {option[0] for option in question.get("selection") or []}
            return raw if raw in options else None
        return None

    def _parse_date_answer(self, raw, label):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise ValidationError(
                _("Svaret på %(question)s måste vara ett datum.", question=label)
            ) from None

    def _parse_datetime_answer(self, raw, label):
        """``datetime-local`` input (requester's wall clock) to the UTC
        string Odoo stores for datetime properties."""
        try:
            local = datetime.fromisoformat(raw)
        except ValueError:
            raise ValidationError(
                _("Svaret på %(question)s måste vara en tidpunkt.", question=label)
            ) from None
        tz = pytz.timezone(request.env.user.tz or "UTC")
        return (
            tz.localize(local.replace(tzinfo=None))
            .astimezone(pytz.utc)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
