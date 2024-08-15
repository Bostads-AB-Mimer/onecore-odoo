from odoo import models, fields, api
from urllib.parse import quote

import base64
import uuid
import requests
import json
import logging

_logger = logging.getLogger(__name__)

class OneCoreMaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    uuid = fields.Char(string='UUID', default=lambda self: str(uuid.uuid4()), readonly=True, copy=False)
    search_by_number = fields.Char('Search')
    search_type = fields.Selection([
        ('leaseId', 'Kontraktsnummer'),
        ('rentalPropertyId', 'Property ID'),
        ('pnr', 'Personnummer (12 siffror)'),
        ('phoneNumber', 'Telefonnummer (10 siffror)'),
    ], string='Search Type', default='leaseId', required=True)

    rental_property_option_id = fields.Many2one('maintenance.rental.property.option', compute='_compute_search', string='Rental Property Option Id', store=True, readonly=False)
    tenant_option_id = fields.Many2one('maintenance.tenant.option', compute='_compute_search', string='Tenant', store=True, readonly=False)
    lease_option_id = fields.Many2one('maintenance.lease.option', compute='_compute_search', string='Lease', store=True, readonly=False)

    # Dependent on rental_property_option_id
    rental_property_id = fields.Char(string='Rental Property ID', store=True)
    address = fields.Char('Address', store=True)
    property_type = fields.Char('Property Type', store=True)
    code = fields.Char('Code', store=True)
    type = fields.Char('Type', store=True)
    area = fields.Char('Size', store=True)
    entrance = fields.Char('Entrance', store=True)
    floor = fields.Char('Floor', store=True)
    has_elevator = fields.Char('Has Elevator', store=True)
    wash_space = fields.Char('Wash Space', store=True)
    estate_code = fields.Char('Estate Code', store=True)
    estate = fields.Char('Estate Caption', store=True)
    building_code = fields.Char('Block Code', store=True)
    building = fields.Char('Block Name', store=True)

    # Dependent on tenant_option_id
    contact_code = fields.Char(string='Contact Code', store=True)
    tenant_id = fields.Char(string='Tenant Id', store=True)
    national_registration_number = fields.Char('National Registration Number', store=True)
    phone_number = fields.Char('Phone Number', store=True)
    email_address = fields.Char('Email Address', store=True)
    is_tenant = fields.Boolean('Is Tenant', store=True)

    # Dependent on lease_option_id
    lease_id = fields.Char(string='Lease Id', store=True, readonly=True)
    lease_type = fields.Char('Lease Type', store=True, readonly=True)
    contract_date = fields.Date('Contract Date', store=True, readonly=True)
    lease_start_date = fields.Date('Lease Start Date', store=True, readonly=True)
    lease_end_date = fields.Date('Lease End Date', store=True, readonly=True)

    # Comes from Mimer (Add more fields for these?)
    pet=fields.Char('Pet', store=True, readonly=True)
    call_between=fields.Char('Call Between', store=True, readonly=True)
    hearing_impaired=fields.Boolean('Hearing Impaired', store=True, readonly=True)
    space_code=fields.Char('Space Code', store=True, readonly=True)
    space_caption=fields.Char('Space Caption', store=True, readonly=True)
    equipment_code=fields.Char('Equipment Code', store=True, readonly=True)
    maintenance_unit_code=fields.Char('Maintenance Unit Code', store=True, readonly=True)
    maintenance_unit_caption=fields.Char('Maintenance Unit Caption', store=True, readonly=True)
    master_key=fields.Boolean('Master Key', store=True, default=True)

    # New fields
    priority_expanded=fields.Selection([('1', '1 dag'), ('5', '5 dagar'), ('7', '7 dagar'), ('10', '10 dagar'), ('14', '2 veckor')], string='Prioritet', required=True, store=True, default='7')


    def fetch_property_data(self, search_by_number, search_type):
        onecore_auth = self.env['onecore.auth']
        base_url = self.env['ir.config_parameter'].get_param(
            'onecore_propertyinfo_url', '')
        params = {'typeOfNumber': search_type}
        url = f"{base_url}{quote(search_by_number, safe='')}"
        try:
            response = onecore_auth.onecore_request(url, params=params)
            response.raise_for_status()
            return response.json().get('data', {})
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    def update_form_options(self, search_by_number, search_type):
        _logger.info("Updating rental property options")
        data = self.fetch_property_data(search_by_number, search_type)
        if data:
            for property in data:
                rental_property_option = self.env['maintenance.rental.property.option'].create({
                    'user_id': self.env.user.id,
                    'name': property['id'],
                    'property_type': property['type'],
                    'address': property['property'].get('address'),
                    'code': property['property'].get('code'),
                    'type': property['property'].get('type'),
                    'area': property['property'].get('area'),
                    'entrance': property['property'].get('entrance'),
                    'floor': property['property'].get('floor'),
                    'has_elevator': property['property'].get('hasElevator'),
                    'wash_space': property['property'].get('washSpace'),
                    'estate_code': property['property'].get('estateCode'),
                    'estate': property['property'].get('estateName'),
                    'building_code': property['property'].get('buildingCode'),
                    'building': property['property'].get('building'),
                })
                for lease in property['leases']:
                    lease_option = self.env['maintenance.lease.option'].create({
                        'user_id': self.env.user.id,
                        'name': lease['leaseId'],
                        'lease_number': lease['leaseNumber'],
                        'rental_property_option_id': rental_property_option.id,
                        'lease_type': lease['type'],
                        'lease_start_date': lease['leaseStartDate'],
                        'lease_end_date': lease['leaseEndDate'],
                        'contract_date': lease['contractDate'],
                        'approval_date': lease['approvalDate'],
                    })
                    for tenant in lease['tenants']:
                        # Find the main phone number
                        phone_number = next((item['phoneNumber'] for item in tenant['phoneNumbers'] if item['isMainNumber'] == 1), None)
                        existing_tenant = self.env['maintenance.tenant.option'].search([('contact_code', '=', tenant['contactCode'])], limit=1)

                        if not existing_tenant:
                          self.env['maintenance.tenant.option'].create({
                            'user_id': self.env.user.id,
                            'name': tenant['firstName'] + " " + tenant['lastName'],
                            'contact_code': tenant['contactCode'],
                            'contact_key': tenant['contactKey'],
                            'national_registration_number': tenant['nationalRegistrationNumber'],
                            'email_address': tenant['emailAddress'],
                            'phone_number': phone_number,
                            'is_tenant': tenant['isTenant'],
                            'tenant_option_id': lease_option.id,
                          })
        else:
            _logger.info("No data found in response.")

    @api.depends('search_by_number', 'search_type')
    def _compute_search(self):
        # Clear existing records for this user
        self.env['maintenance.rental.property.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['maintenance.lease.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['maintenance.tenant.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        for record in self:
            if not record.search_by_number:
                record.search_by_number = False
                continue
            record.update_form_options(record.search_by_number, record.search_type)
            property_records = self.env['maintenance.rental.property.option'].search([('user_id', '=', self.env.user.id)])
            if property_records:
                record.rental_property_option_id = property_records[0].id
            lease_records = self.env['maintenance.lease.option'].search([('user_id', '=', self.env.user.id)])
            if lease_records:
                record.lease_option_id = lease_records[0].id
            tenant_records = self.env['maintenance.tenant.option'].search([('user_id', '=', self.env.user.id)])
            if tenant_records:
                record.tenant_option_id = tenant_records[0].id

    @api.onchange('rental_property_option_id')
    def _onchange_rental_property_option_id(self):
        if self.rental_property_option_id:
            self.rental_property_id = self.rental_property_option_id.name
            self.address = self.rental_property_option_id.address
            self.property_type = self.rental_property_option_id.property_type
            self.code = self.rental_property_option_id.code
            self.type = self.rental_property_option_id.type
            self.area = self.rental_property_option_id.area
            self.entrance = self.rental_property_option_id.entrance
            self.floor = self.rental_property_option_id.floor
            self.has_elevator = self.rental_property_option_id.has_elevator
            self.wash_space = self.rental_property_option_id.wash_space
            self.estate_code = self.rental_property_option_id.estate_code
            self.estate = self.rental_property_option_id.estate
            self.building_code = self.rental_property_option_id.building_code
            self.building = self.rental_property_option_id.building

    @api.onchange('lease_option_id')
    def _onchange_lease_option_id(self):
        if self.lease_option_id:
            self.lease_id = self.lease_option_id.name
            self.lease_type = self.lease_option_id.lease_type
            self.contract_date = self.lease_option_id.contract_date
            self.lease_start_date = self.lease_option_id.lease_start_date
            self.lease_end_date = self.lease_option_id.lease_end_date

    @api.onchange('tenant_option_id')
    def _onchange_tenant_option_id(self):
        if self.tenant_option_id:
            self.contact_code = self.tenant_option_id.contact_code
            self.national_registration_number = self.tenant_option_id.national_registration_number
            self.phone_number = self.tenant_option_id.phone_number
            self.email_address = self.tenant_option_id.email_address
            self.is_tenant = self.tenant_option_id.is_tenant
            self.tenant_id = self.tenant_option_id.name

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"Creating maintenance requests: {vals_list}")
        for vals in vals_list:
            if 'rental_property_option_id' in vals:
                vals['rental_property_id'] = self.rental_property_option_id.name
            if 'lease_option_id' in vals:
                vals['lease_id'] = self.lease_option_id.name
            if 'tenant_option_id' in vals:
                vals['tenant_id'] = self.tenant_option_id.name
                vals['contact_code'] = self.tenant_option_id.contact_code
            if 'images' in vals:
                images = vals.pop('images')

        maintenance_requests = super().create(vals_list)
        for request in maintenance_requests:
            for image in images:
              file_data = base64.b64decode(image['Base64String'])
              attachment = self.env['ir.attachment'].create({
                  'name': image['Filename'],
                  'type': 'binary',
                  'datas': base64.b64encode(file_data),
                  'res_model': 'maintenance.request',
                  'res_id': request.id,
                  'mimetype': 'application/octet-stream'
              })
            if request.owner_user_id or request.user_id:
                request._add_followers()
            if request.equipment_id and not request.maintenance_team_id:
                request.maintenance_team_id = request.equipment_id.maintenance_team_id
            if request.close_date and not request.stage_id.done:
                request.close_date = False
            if not request.close_date and request.stage_id.done:
                request.close_date = fields.Date.today()
            maintenance_requests.activity_update()

            # The below is  a Mimer added API-call to create errands in other app to test out a webhook, the api call to apps.mimer.nu is only to be used for testing.
            # Created errands will be created in a test app and can be viewed at https://apps.mimer.nu/version-test/odootest/'''


            # Only proceed if rental_property_option_id is present
            if request.rental_property_option_id:
                ICP = self.env['ir.config_parameter'].sudo()
                token = ICP.get_param('x_webhook_bearer_token', default=None) #Note that this token needs to be added in the odoo interface, using developersettings.
                if not token:
                    _logger.error("Bearer token is not set in system parameters.")
                    return maintenance_requests

                webhook_url = "https://apps.mimer.nu/version-test/api/1.1/wf/createerrand"
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }

                 # Convert HTML to plain text
                description_text = html2plaintext(request.description) if request.description else ""

                data = {
                    "rentalObjectId": request.rental_property_option_id.name,
                    "title": request.name,
                    "odooId": str(request.id),  # The unique Odoo ID
                    "description": description_text,
                    "state": request.stage_id.name,
                }
                try:
                    response = requests.post(webhook_url, headers=headers, json=data)
                    _logger.info(f"Webhook sent. Status Code: {response.status_code}, Response: {response.text}")
                except Exception as e:
                    _logger.error(f"Failed to send webhook: {e}")
            else:
                _logger.info(f"Webhook not sent. rental_property_option_id is missing for Maintenance Request ID: {request.id}")

        return maintenance_requests

    def write(self, vals):
        if 'kanban_state' not in vals and 'stage_id' in vals:
            vals['kanban_state'] = 'normal'
        if 'stage_id' in vals and self.maintenance_type == 'preventive' and self.recurring_maintenance and self.env['maintenance.stage'].browse(vals['stage_id']).done:
            schedule_date = self.schedule_date or fields.Datetime.now()
            schedule_date += relativedelta(**{f"{self.repeat_unit}s": self.repeat_interval})
            if self.repeat_type == 'forever' or schedule_date.date() <= self.repeat_until:
                self.copy({'schedule_date': schedule_date})
        res = super().write(vals)

        if vals.get('owner_user_id') or vals.get('user_id'):
            self._add_followers()
        if 'stage_id' in vals:
            self.filtered(lambda m: m.stage_id.done).write({'close_date': fields.Date.today()})
            self.filtered(lambda m: not m.stage_id.done).write({'close_date': False})
            self.activity_feedback(['maintenance.mail_act_maintenance_request'])
            self.activity_update()
        if vals.get('user_id') or vals.get('schedule_date'):
            self.activity_update()
        if self._need_new_activity(vals):
            # need to change description of activity also so unlink old and create new activity
            self.activity_unlink(['maintenance.mail_act_maintenance_request'])
            self.activity_update()

        # The below is  a Mimer added API-call to update errands in other app to test out a webhook, the api call to apps.mimer.nu is only to be used for testing.
        # Created errands will be created in a test app and can be viewed at https://apps.mimer.nu/version-test/odootest/

        for request in self:
            # Only proceed if rental_property_option_id is present
            if request.rental_property_option_id:
                ICP = request.env['ir.config_parameter'].sudo()
                token = ICP.get_param('x_webhook_bearer_token', default=None) #Note that this token needs to be added in the odoo interface, using developersettings.
                if not token:
                    _logger.error("Bearer token is not set in system parameters.")
                    continue  # Skip this iteration

                webhook_url = "https://apps.mimer.nu/version-test/api/1.1/wf/updateErrand"
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }

                # Assuming you want to update the same fields as those you send when creating an errand
                description_text = html2plaintext(request.description) if request.description else ""
                data = {
                    "odooId": str(request.id),
                    "rentalObjectId": request.rental_property_option_id.name,
                    "title": request.name,
                    "description": description_text,
                    "state": request.stage_id.name,
                }

                try:
                    response = requests.post(webhook_url, headers=headers, json=data)
                    _logger.info(f"Webhook for update sent. Status Code: {response.status_code}, Response: {response.text}")
                except Exception as e:
                    _logger.error(f"Failed to send update webhook: {e}")

        return res


    #Mimer created webhook to delete errands from external testapp. https://apps.mimer.nu/version-test/odootest/
    def unlink(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('x_webhook_bearer_token', default=None)
        if not token:
            _logger.error("Bearer token is not set in system parameters.")
        else:
            for request in self:
                if request.rental_property_option_id:
                    webhook_url = "https://apps.mimer.nu/version-test/api/1.1/wf/deleteerrand"
                    headers = {
                        'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/json'
                    }
                    data = {"odooId": str(request.id)}
                    try:
                        response = requests.post(webhook_url, headers=headers, json=data)
                        if response.status_code != 200:
                            _logger.error(f"Webhook call failed: {response.text}")
                    except Exception as e:
                        _logger.error(f"Error calling webhook: {str(e)}")
                else:
                    _logger.info(f"Webhook not sent. rental_property_option_id is missing for Maintenance Request ID: {request.id}")

        return super().unlink()

class OnecoreMaintenanceRentalPropertyOption(models.Model):
    _name = 'maintenance.rental.property.option'
    _description = 'Rental Property Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    property_type = fields.Char('Property Type', required=True)
    address = fields.Char('Address')
    code = fields.Char('Code')
    type = fields.Char('Type')
    area = fields.Char('Size')
    entrance = fields.Char('Entrance')
    floor = fields.Char('Floor')
    has_elevator = fields.Char('Has Elevator')
    wash_space = fields.Char('Wash Space')
    estate_code = fields.Char('Estate Code')
    estate = fields.Char('Estate Name')
    building_code = fields.Char('Block Code')
    building = fields.Char('Block Name')
    lease_ids = fields.One2many('maintenance.lease.option', 'rental_property_option_id', string='Leases')

class OnecoreMaintenanceLeaseOption(models.Model):
    _name = 'maintenance.lease.option'
    _description = 'Lease Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    lease_number = fields.Char('Lease Number', required=True)
    rental_property_option_id = fields.Many2one('maintenance.rental.property.option', string='Rental Property Option')
    lease_type = fields.Char('Type', required=True)
    lease_start_date = fields.Date('Lease Start Date', required=True)
    lease_end_date = fields.Date('Lease End Date')
    tenants = fields.One2many('maintenance.tenant.option', 'tenant_option_id', string='Tenants')
    notice_given_by = fields.Char('Notice Given By')
    notice_date = fields.Date('Notice Date')
    notice_time_tenant = fields.Integer('Notice Time Tenant')
    preferred_move_out_date = fields.Date('Preferred Move Out Date')
    termination_date = fields.Date('Termination Date')
    contract_date = fields.Date('Contract Date', required=True)
    last_debit_date = fields.Date('Last Debit Date')
    approval_date = fields.Date('Approval Date')

class OnecoreMaintenanceTenantOption(models.Model):
    _name = 'maintenance.tenant.option'
    _description = 'Tenant Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    contact_code = fields.Char('Contact Code', required=True)
    contact_key = fields.Char('Contact Key', required=True)
    national_registration_number = fields.Char('National Registration Number', required=True)
    phone_number = fields.Char('Phone Number', required=True)
    email_address = fields.Char('Email Address', required=True)
    is_tenant = fields.Boolean('Is Tenant', default=True)
    tenant_option_id = fields.Many2one('maintenance.lease.option', string='Lease Option')
