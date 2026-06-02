from odoo import _, api, fields, models

import logging
import requests
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)


class OneCoreMailMessage(models.Model):
    _inherit = "mail.message"

    is_dialog_unread_for_user = fields.Boolean(
        string="Olästa i dialogen för aktuell användare",
        compute="_compute_is_dialog_unread_for_user",
        store=False,
    )

    @api.depends("author_id", "date", "message_type", "subtype_id", "model", "res_id")
    def _compute_is_dialog_unread_for_user(self):
        # Highlights log notes from the opposite party (internal Mimer vs
        # external contractor) on maintenance.request until acknowledged via
        # action_acknowledge_dialog on the parent record.
        for message in self:
            message.is_dialog_unread_for_user = False

        external_group = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor",
            raise_if_not_found=False,
        )
        note_subtype = self.env.ref("mail.mt_note", raise_if_not_found=False)
        if not external_group or not note_subtype:
            return

        candidates = self.filtered(
            lambda m: m.model == "maintenance.request"
            and m.message_type == "comment"
            and m.subtype_id.id == note_subtype.id
            and m.author_id
            and m.res_id
        )
        if not candidates:
            return

        is_external_user = self.env.user.has_group(
            "onecore_maintenance_extension.group_external_contractor"
        )
        ack_field = (
            "internal_dialog_ack_at" if is_external_user else "supplier_dialog_ack_at"
        )

        request_ids = list(set(candidates.mapped("res_id")))
        requests = self.env["maintenance.request"].browse(request_ids)
        ack_by_request = {req.id: req[ack_field] for req in requests}

        author_ids = list(set(candidates.mapped("author_id").ids))
        external_users = self.env["res.users"].search(
            [
                ("partner_id", "in", author_ids),
                ("all_group_ids", "in", external_group.id),
            ]
        )
        external_partner_ids = set(external_users.mapped("partner_id").ids)

        for message in candidates:
            author_is_external = message.author_id.id in external_partner_ids
            # Only highlight messages from the opposite party.
            if is_external_user == author_is_external:
                continue
            ack_at = ack_by_request.get(message.res_id)
            if ack_at and message.date and message.date <= ack_at:
                continue
            message.is_dialog_unread_for_user = True

    def _to_store_defaults(self, target):
        # Exposes is_dialog_unread_for_user to the OWL chatter so the Message
        # component can toggle the orange-background CSS class.
        return super()._to_store_defaults(target) + ["is_dialog_unread_for_user"]

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
