# -*- coding: utf-8 -*-
"""Wizard for reporting time on a maintenance request to the time reporting app."""

import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .services import (
    ExternalContractorService,
    ManagementAreaService,
    TimeReportService,
)
from .utils import validators

_logger = logging.getLogger(__name__)

WORK_ORDER_PREFIX = "od-"
DEFAULT_TZ = "Europe/Stockholm"
MAX_HOURS = 24

# job type key -> (typeOfJob sent to the app, costPool)
JOB_TYPES = {
    "repair_appliance": ("Reparation Vitvara", "622"),
    "painting": ("Måleri", "624"),
    "carpentry": ("Snickeri", "622"),
    "operations": ("Drift", "621"),
}

WEEKDAYS = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"]

PREVIOUS_STEP = {"hours": "date", "job_type": "hours"}

# Same parameter as the old "Öppna tidrapport" button; logging in there
# creates the user in the app.
APP_URL_PARAM = "time_report_base_url"
DEFAULT_APP_URL = "https://apps.mimer.nu/tidsrapportering"
APP_USER_MISSING_MESSAGE = (
    "Användaren saknas i tidsrapporteringsappen apps.mimer.nu (Bubble). "
    "Obs! Det räcker med att logga in där för att skapa användaren. "
    "Logga in via knappen nedan och klicka sedan på \"Kontrollera igen\"."
)


class MaintenanceTimeReportWizard(models.TransientModel):
    _name = "maintenance.time.report.wizard"
    _description = "Tidsrapportering"

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Underhållsärende", required=True
    )
    property_code = fields.Char("Fastighetsnummer", readonly=True)
    cost_center_code = fields.Char("KST", readonly=True)
    # The request has no property: the user must search one up before the
    # report can be sent (same OneCore search as "Fastighetsnamn" on requests).
    property_missing = fields.Boolean(readonly=True)
    property_search = fields.Char("Sök fastighet")
    property_option_ids = fields.Many2many("maintenance.property.option")
    property_option_id = fields.Many2one(
        "maintenance.property.option",
        string="Fastighet",
        domain="[('id', 'in', property_option_ids)]",
    )
    work_order_id = fields.Char("Ärendenummer", readonly=True)
    # Checked once when the modal opens so the user is warned before filling
    # in the steps; the service logs the missing parameter.
    api_configured = fields.Boolean(
        default=lambda self: bool(TimeReportService(self.env).get_api_url())
    )
    # Set when the modal opens and the user can't report: missing in the time
    # reporting app (or it couldn't be asked). Shown as a banner, blocks steps.
    user_check_message = fields.Char(readonly=True)
    app_user_missing = fields.Boolean(readonly=True)

    step = fields.Selection(
        [("date", "Välj datum"), ("hours", "Antal timmar"), ("job_type", "Typ av jobb")],
        default="date",
        required=True,
    )
    date_for_work = fields.Date("Datum", default=fields.Date.context_today)
    weekday_label = fields.Char("Veckodag", compute="_compute_weekday_label")
    hours_spent = fields.Float("Antal timmar", digits=(4, 2))
    job_type = fields.Selection(
        [(key, label) for key, (label, _pool) in JOB_TYPES.items()],
        string="Typ av jobb",
    )

    @api.depends("date_for_work")
    def _compute_weekday_label(self):
        for wizard in self:
            wizard.weekday_label = (
                WEEKDAYS[wizard.date_for_work.weekday()]
                if wizard.date_for_work
                else False
            )

    @api.onchange("property_search")
    def _onchange_property_search(self):
        search = (self.property_search or "").strip()
        if not self.property_missing or not validators["propertyName"](search):
            return
        try:
            properties = self.env["maintenance.request"].get_core_api().fetch_properties(
                search, "Fastighet"
            )
        except Exception as err:  # network, auth, JSON
            _logger.warning("Property search for time report failed: %s", err)
            return {
                "warning": {
                    "title": "Sökningen misslyckades",
                    "message": "Kunde inte söka fastigheter just nu. Försök igen.",
                }
            }

        options = self.env["maintenance.property.option"]
        for item in properties or []:
            prop = item["property"]
            options |= options.create(
                {
                    "user_id": self.env.user.id,
                    "designation": prop["designation"],
                    "code": prop["code"],
                }
            )
        self.property_option_ids = options
        self.property_option_id = options[:1]
        if not options:
            return {
                "warning": {
                    "title": "Inga träffar",
                    "message": f'Hittade ingen fastighet för "{search}".',
                }
            }

    @api.onchange("property_option_id")
    def _onchange_property_option_id(self):
        if not self.property_missing:
            return
        self.property_code = self.property_option_id.code or False
        self.cost_center_code = False
        if self.property_code:
            _ok, values = ManagementAreaService(self.env).fetch_for_property(
                self.property_code
            )
            self.cost_center_code = (values or {}).get("cost_center_code") or False

    @api.model_create_multi
    def create(self, vals_list):
        self._check_not_external_contractor()
        wizards = super().create(vals_list)
        if wizards and TimeReportService(self.env).get_api_url():
            wizards._refresh_user_check()
        return wizards

    def _refresh_user_check(self):
        try:
            self._check_time_report_user()
            vals = {"user_check_message": False, "app_user_missing": False}
        except UserError as err:
            vals = {
                "user_check_message": err.args[0],
                "app_user_missing": err.args[0] == APP_USER_MISSING_MESSAGE,
            }
        self.write(vals)

    def _check_time_report_user(self):
        """Raise unless the current user exists in the time reporting app;
        otherwise the report would land there without a contractor."""
        email = self.env.user.email
        if not email:
            raise UserError(
                "Din användare saknar e-postadress och kan inte rapportera tid."
            )
        if not TimeReportService(self.env).user_exists(email):
            raise UserError(APP_USER_MISSING_MESSAGE)

    def action_open_time_report_app(self):
        url = (
            self.env["ir.config_parameter"].sudo().get_param(APP_URL_PARAM)
            or DEFAULT_APP_URL
        )
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def action_recheck_user(self):
        self._refresh_user_check()
        return self._reopen()

    def _check_not_external_contractor(self):
        if ExternalContractorService(self.env).is_external_contractor():
            raise AccessError(
                "Tidsrapportering är inte tillgänglig för externa entreprenörer."
            )

    def _reopen(self):
        self.ensure_one()
        return {
            "name": "Tidsrapportering",
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    # ==================== Step: date ====================

    def _set_date(self, date):
        if self.user_check_message:
            raise UserError(self.user_check_message)
        if not self.property_code:
            raise UserError("Välj en fastighet innan du rapporterar tid.")
        if not date:
            raise UserError("Välj ett datum.")
        if date > fields.Date.context_today(self):
            raise UserError("Du kan inte rapportera tid för ett datum framåt i tiden.")
        self.write({"date_for_work": date, "step": "hours"})
        return self._reopen()

    def action_today(self):
        return self._set_date(fields.Date.context_today(self))

    def action_yesterday(self):
        return self._set_date(fields.Date.context_today(self) - timedelta(days=1))

    def action_confirm_date(self):
        return self._set_date(self.date_for_work)

    # ==================== Step: hours ====================

    def action_confirm_hours(self):
        if not 0 < self.hours_spent <= MAX_HOURS:
            raise UserError(f"Ange antal timmar mellan 0 och {MAX_HOURS}.")
        self.step = "job_type"
        return self._reopen()

    def action_back(self):
        self.step = PREVIOUS_STEP.get(self.step, "date")
        return self._reopen()

    # ==================== Step: job type ====================

    def action_submit(self):
        return self._submit()

    # ==================== Submit ====================

    def _date_for_work_iso(self):
        """Chosen date with the current local time, e.g. 2025-06-19T12:21:00+02:00."""
        # pytz, not zoneinfo: zoneinfo needs the tzdata package on Windows.
        try:
            tz = pytz.timezone(self.env.user.tz or DEFAULT_TZ)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone(DEFAULT_TZ)
        now = datetime.now(tz)
        moment = datetime.combine(self.date_for_work, now.time().replace(microsecond=0))
        # localize() picks the offset valid on the chosen date (summer/winter time).
        return tz.localize(moment).isoformat()

    def _build_payload(self):
        self.ensure_one()
        type_of_job, cost_pool = JOB_TYPES[self.job_type]
        return {
            "contractorEmail": self.env.user.email,
            "costPool": cost_pool,
            "dateForWork": self._date_for_work_iso(),
            "hoursSpent": self.hours_spent,
            "KST": self.cost_center_code,
            "propertyCode": self.property_code,
            "typeOfJob": type_of_job,
            "workOrderId": self.work_order_id,
        }

    def _check_ready_to_submit(self):
        if not self.property_code:
            raise UserError("Välj en fastighet innan du rapporterar tid.")
        if not self.cost_center_code:
            if self.property_missing:
                raise UserError(
                    "Hittade inget distrikt (KST) för den valda fastigheten i "
                    "OneCore. Välj en annan fastighet eller kontakta en administratör."
                )
            raise UserError(
                "Ärendet saknar distrikt (KST). Klicka på \"Tilldela resursgrupp\" "
                "på ärendet och försök igen."
            )
        if not self.date_for_work or not self.hours_spent or not self.job_type:
            raise UserError("Välj datum, antal timmar och typ av jobb.")

    def _submit(self):
        self.ensure_one()
        self._check_not_external_contractor()
        self._check_ready_to_submit()
        self._check_time_report_user()

        TimeReportService(self.env).create_time_report(self._build_payload())

        type_of_job = JOB_TYPES[self.job_type][0]
        hours = f"{self.hours_spent:g}"
        date = fields.Date.to_string(self.date_for_work)
        self.maintenance_request_id.message_post(
            body=f"Tid rapporterad: {hours} h {type_of_job} för {date}.",
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Tidsrapportering",
                "message": f"{hours} h {type_of_job} rapporterade för {date}.",
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
