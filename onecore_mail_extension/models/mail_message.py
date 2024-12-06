
from odoo import _, api, fields, models

import logging
import requests

_logger = logging.getLogger(__name__)

class OneCoreMailMessage(models.Model):
    _inherit = "mail.message"

    message_type = fields.Selection(
        selection_add=[
            ("from_tenant", "From tenant"),
            ("tenant_sms", "Sent to tenant by SMS"),
            ("tenant_mail", "Sent to tenant by email"),
            ("tenant_mail_and_sms", "Sent to tenant by email and SMS"),
            ("tenant_sms_error", "Sent to tenant by SMS, but sending failed"),
            ("tenant_mail_error", "Sent to tenant by email, but sending failed"),
            ("tenant_mail_and_sms_error", "Sent to tenant by email and SMS, but sending failed"),
            ("tenant_mail_ok_and_sms_error", "Sent to tenant by email and SMS, but sending failed"),
            ("tenant_mail_error_and_sms_ok", "Sent to tenant by email and SMS, but sending failed"),

        ],
        ondelete={
            "from_tenant": "set default",
            "tenant_sms": "set default",
            "tenant_mail": "set default",
            "tenant_mail_and_sms": "set default",
            "tenant_sms_error": "set default",
            "tenant_mail_error": "set default",
            "tenant_mail_and_sms_error": "set default",
            "tenant_mail_ok_and_sms_error": "set default",
            "tenant_mail_error_and_sms_ok": "set default",
        },
    )

    def _send_email(self, to_email, subject, message):
        onecore_auth = self.env['onecore.auth']
        base_url = self.env['ir.config_parameter'].get_param(
            'onecore_base_url', '')
        data = {
            'to': to_email,
            'subject': subject,
            'message': message
        }
        url = f"{base_url}/sendTicketMessageEmail"

        try:
            response = onecore_auth.onecore_request('POST', url, data=data)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    
    def _send_sms(self, phone_number, message):
        onecore_auth = self.env['onecore.auth']
        base_url = self.env['ir.config_parameter'].get_param(
            'onecore_base_url', '')
        data = {
            'phoneNumber': phone_number,
            'message': message
        }
        url = f"{base_url}/sendTicketMessageSms"

        try:
            response = onecore_auth.onecore_request('POST', url, data=data)
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
            the_record = self.env['maintenance.request'].search([('id', '=', values['res_id'])])
            
            if values['message_type'] == 'tenant_sms':
                send_sms_result = self._send_sms(the_record.tenant_id.phone_number, values['body'].replace('<br>', '\n'))
                
                if send_sms_result is None:
                    values['message_type'] = 'tenant_sms_error'
            
            if values['message_type'] == 'tenant_mail':
                subject = f"Ang. serviceanmälan: {the_record.name}"
                body = values['body'].replace('<br>', '\\n')
                
                send_email_result = self._send_email(the_record.tenant_id.email_address, subject, body)
                
                if send_email_result is None:
                    values['message_type'] = 'tenant_mail_error'
            
            if values['message_type'] == 'tenant_mail_and_sms':
                subject = f"Ang. serviceanmälan: {the_record.name}"
                body = values['body'].replace('<br>', '\\n')
                
                send_email_result = self._send_email(the_record.tenant_id.email_address, subject, body)
                send_sms_result = self._send_sms(the_record.tenant_id.phone_number, body)
                
                if send_email_result is None and send_sms_result is not None:
                    values['message_type'] = 'tenant_mail_error_and_sms_ok'
                if send_sms_result is None and send_email_result is not None:
                    values['message_type'] = 'tenant_mail_ok_and_sms_error'
                if send_email_result is None and send_sms_result is None:
                    values['message_type'] = 'tenant_mail_and_sms_error'           

        messages = super(OneCoreMailMessage, self).create(values_list)

        return messages

   