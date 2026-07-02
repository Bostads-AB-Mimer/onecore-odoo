from odoo import _, api, fields, models
from odoo.exceptions import AccessError

import logging
import requests
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)


class OneCoreMailMessage(models.Model):
    _inherit = "mail.message"

    informs_opposite_party = fields.Boolean(
        string="Informera motparten",
        default=False,
        help="Loggnoteringar som markeras här visar dialogindikatorn (orange) "
        "för motparten — Mimer ⇄ extern entreprenör.",
    )
    is_dialog_unread_for_side = fields.Boolean(
        string="Okvitterad dialognotering",
        compute="_compute_is_dialog_unread_for_side",
        store=False,
    )
    pinned = fields.Boolean(
        string="Fäst",
        default=False,
        index=True,
        help="Fästa noteringar visas högst upp i loggen för alla som öppnar ärendet.",
    )
    pinned_by_id = fields.Many2one(
        "res.users",
        string="Fäst av",
    )
    pinned_at = fields.Datetime(
        string="Fäst datum",
    )
    pinned_by_name = fields.Char(
        string="Fäst av (namn)",
        compute="_compute_pinned_by_name",
        store=False,
    )
    can_pin = fields.Boolean(
        string="Får fästa",
        compute="_compute_can_pin",
        store=False,
    )

    @api.depends(
        "author_id",
        "date",
        "message_type",
        "subtype_id",
        "model",
        "res_id",
        "informs_opposite_party",
    )
    def _compute_is_dialog_unread_for_side(self):
        # Highlights log notes from the opposite party (internal Mimer vs
        # external contractor) on maintenance.request until acknowledged via
        # action_acknowledge_dialog on the parent record. The classification is
        # owned by maintenance.request._dialog_unread_message_ids so the rules
        # are not duplicated here.
        for message in self:
            message.is_dialog_unread_for_side = False

        # onecore_mail_extension does not declare a dependency on the
        # maintenance module, so guard against it being absent.
        if "maintenance.request" not in self.env:
            return

        unread_ids = self.env["maintenance.request"]._dialog_unread_message_ids(self)
        for message in self:
            if message.id in unread_ids:
                message.is_dialog_unread_for_side = True

    @api.depends("pinned_by_id")
    def _compute_pinned_by_name(self):
        for message in self:
            message.pinned_by_name = message.pinned_by_id.name or ""

    @api.depends_context("uid")
    def _compute_can_pin(self):
        # Internal handlers may pin; external contractors may not. Mirrors the
        # group check already used in create(). has_group returns False when the
        # maintenance module (and thus the group) is absent. depends_context("uid")
        # is required so the cache is keyed per user — without it, Odoo caches the
        # first-computed value and reuses it for every user in the same transaction.
        is_external = self.env.user.has_group(
            "onecore_maintenance_extension.group_external_contractor"
        )
        for message in self:
            message.can_pin = not is_external

    def _to_store_defaults(self, target):
        # Exposes is_dialog_unread_for_side (dialog highlight) and the pin state
        # (pinned/pinned_at/pinned_by_name/can_pin) to the OWL chatter store.
        return super()._to_store_defaults(target) + [
            "is_dialog_unread_for_side",
            "pinned",
            "pinned_at",
            "pinned_by_name",
            "can_pin",
        ]

    def action_toggle_pin(self):
        # Shared pin toggle for the chatter "Fästa" section. Internal handlers
        # only; external contractors are blocked here (the front-end also hides
        # the button via can_pin). Writes with sudo because pinning is a
        # cross-user action on messages the caller does not own, and mail.message
        # write ACLs otherwise restrict edits to the author.
        self.ensure_one()
        if self.env.user.has_group(
            "onecore_maintenance_extension.group_external_contractor"
        ):
            raise AccessError(_("Du har inte behörighet att fästa noteringar."))
        if self.pinned:
            self.sudo().write(
                {"pinned": False, "pinned_by_id": False, "pinned_at": False}
            )
        else:
            self.sudo().write(
                {
                    "pinned": True,
                    "pinned_by_id": self.env.user.id,
                    "pinned_at": fields.Datetime.now(),
                }
            )
        return {
            "pinned": self.pinned,
            "pinned_at": self.pinned_at,
            "pinned_by_name": self.pinned_by_name,
        }

    message_type = fields.Selection(
        selection_add=[
            ("from_tenant", "From tenant"),
            ("tenant_sms", "Sent to tenant by SMS"),
            ("tenant_mail", "Sent to tenant by email"),
            ("tenant_mail_and_sms", "Sent to tenant by email and SMS"),
            ("failed_tenant_sms", "Sent to tenant by SMS, but sending failed"),
            ("failed_tenant_mail", "Sent to tenant by email, but sending failed"),
            (
                "failed_tenant_mail_and_sms",
                "Sent to tenant by email and SMS, but both sending failed",
            ),
            (
                "tenant_mail_ok_and_sms_failed",
                "Sent to tenant by email and SMS, but sending SMS failed",
            ),
            (
                "tenant_mail_failed_and_sms_ok",
                "Sent to tenant by email and SMS, but sending email failed",
            ),
        ],
        ondelete={
            "from_tenant": "set default",
            "tenant_sms": "set default",
            "tenant_mail": "set default",
            "tenant_mail_and_sms": "set default",
            "failed_tenant_sms": "set default",
            "failed_tenant_mail": "set default",
            "failed_tenant_mail_and_sms": "set default",
            "tenant_mail_ok_and_sms_failed": "set default",
            "tenant_mail_failed_and_sms_ok": "set default",
        },
    )

    def get_core_api(self):
        return core_api.CoreApi(self.env)

    def _send_email(self, to_email, subject, text, team_name=None):
        data = {
            "to": to_email,
            "subject": subject,
            "text": text,
            "externalContractorName": team_name,
        }

        try:
            response = self.get_core_api().request(
                "POST", "/work-orders/send-email", data=data
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    def _send_sms(self, phone_number, text, team_name=None):
        data = {
            "phoneNumber": phone_number,
            "text": text,
            "externalContractorName": team_name,
        }

        try:
            response = self.get_core_api().request(
                "POST", "/work-orders/send-sms", data=data
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values["message_type"].startswith("tenant_"):
                the_record = self.env["maintenance.request"].search(
                    [("id", "=", values["res_id"])]
                )
                subject = f"Ang. serviceanmälan: {the_record.name}"
                body = values["body"].replace("<br>", "\\n")

                team_name = (
                    the_record.maintenance_team_id.name
                    if self.env.user.has_group(
                        "onecore_maintenance_extension.group_external_contractor"
                    )
                    else None
                )

                # send by sms
                if values["message_type"] == "tenant_sms":
                    send_sms_result = self._send_sms(
                        the_record.tenant_id.phone_number,
                        body,
                        team_name,
                    )

                    if send_sms_result is None:
                        values["message_type"] = "failed_tenant_sms"

                # send by email
                if values["message_type"] == "tenant_mail":
                    send_email_result = self._send_email(
                        the_record.tenant_id.email_address,
                        subject,
                        body,
                        team_name,
                    )

                    if send_email_result is None:
                        values["message_type"] = "failed_tenant_mail"

                # send by email and sms
                if values["message_type"] == "tenant_mail_and_sms":
                    send_email_result = self._send_email(
                        the_record.tenant_id.email_address, subject, body, team_name
                    )
                    send_sms_result = self._send_sms(
                        the_record.tenant_id.phone_number, body, team_name
                    )

                    if send_email_result is None and send_sms_result is not None:
                        values["message_type"] = "tenant_mail_failed_and_sms_ok"
                    if send_sms_result is None and send_email_result is not None:
                        values["message_type"] = "tenant_mail_ok_and_sms_failed"
                    if send_email_result is None and send_sms_result is None:
                        values["message_type"] = "failed_tenant_mail_and_sms"

        messages = super(OneCoreMailMessage, self).create(values_list)

        return messages
