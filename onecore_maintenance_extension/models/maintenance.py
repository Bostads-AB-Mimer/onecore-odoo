from odoo import models, fields, api, tools
from urllib.parse import quote

import base64
import uuid
import requests
import json
import logging
import os

_logger = logging.getLogger(__name__)

def is_local():
    return os.getenv('ENV') == 'local'

class OneCoreMaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    uuid = fields.Char(string='UUID', default=lambda self: str(uuid.uuid4()), readonly=True, copy=False)
    search_by_number = fields.Char('Search', store=False)
    search_type = fields.Selection([
        ('leaseId', 'Kontraktsnummer'),
        ('rentalObjectId', 'Hyresobjekt'),
        ('contactCode', 'Kundnummer'),
        ('pnr', 'Personnummer (12 siffror)'),
        ('phoneNumber', 'Telefonnummer (10 siffror)'),
    ], string='Search Type', default='pnr', required=True, store=False)

    rental_property_option_id = fields.Many2one('maintenance.rental.property.option', compute='_compute_search', string='Rental Property Option Id', domain=lambda self: [('user_id', '=', self.env.user.id)], readonly=False)
    maintenance_unit_option_id = fields.Many2one('maintenance.maintenance.unit.option', compute='_compute_search', string='Maintenance Unit Option', domain=lambda self: [('user_id', '=', self.env.user.id)], readonly=False)
    tenant_option_id = fields.Many2one('maintenance.tenant.option', compute='_compute_search', string='Tenant', domain=lambda self: [('user_id', '=', self.env.user.id)], readonly=False)
    lease_option_id = fields.Many2one('maintenance.lease.option', compute='_compute_search', string='Lease', domain=lambda self: [('user_id', '=', self.env.user.id)], readonly=False)

    #    RENTAL PROPERTY  ---------------------------------------------------------------------------------------------------------------------

    rental_property_id = fields.Many2one('maintenance.rental.property', store=True, string='Hyresobjekt')

    rental_property_name = fields.Char('Hyresobjekt Namn', related='rental_property_id.name', depends=['rental_property_id'])
    address = fields.Char('Adress', related='rental_property_id.address', depends=['rental_property_id'])
    property_type = fields.Char('Fastighetstyp', related='rental_property_id.property_type', depends=['rental_property_id'])
    code = fields.Char('Kod', related='rental_property_id.code', depends=['rental_property_id'])
    type = fields.Char('Typ', related='rental_property_id.type', depends=['rental_property_id'])
    area = fields.Char('Yta', related='rental_property_id.area', depends=['rental_property_id'])
    entrance = fields.Char('Ingång', related='rental_property_id.entrance', depends=['rental_property_id'])
    floor = fields.Char('Våning', related='rental_property_id.floor', depends=['rental_property_id'])
    has_elevator = fields.Char('Hiss', related='rental_property_id.has_elevator', depends=['rental_property_id'])
    wash_space = fields.Char('Tvättutrymme', related='rental_property_id.wash_space', depends=['rental_property_id'])
    estate_code = fields.Char('Fastighetskod', related='rental_property_id.estate_code', depends=['rental_property_id'])
    estate = fields.Char('Fastighet', related='rental_property_id.estate', depends=['rental_property_id'])
    building_code = fields.Char('Kvarterskod', related='rental_property_id.building_code', depends=['rental_property_id'])
    building = fields.Char('Kvarter', related='rental_property_id.building', depends=['rental_property_id'])

    #    MAINTENANCE UNIT ---------------------------------------------------------------------------------------------------------------------

    maintenance_unit_id = fields.Many2one('maintenance.maintenance.unit', string='Maintenance Unit ID', store=True)

    maintenance_unit_type = fields.Char('Utrymmestyp', related='maintenance_unit_id.type', depends=['maintenance_unit_id'])
    maintenance_unit_code=fields.Char('Utrymmeskod', related='maintenance_unit_id.code', depends=['maintenance_unit_id'])
    maintenance_unit_caption=fields.Char('Utrymme', related='maintenance_unit_id.caption', depends=['maintenance_unit_id'])

    #   TENANT  ---------------------------------------------------------------------------------------------------------------------

    tenant_id = fields.Many2one('maintenance.tenant', string='Hyresgäst ID', store=True)

    tenant_name = fields.Char('Namn', related='tenant_id.name', depends=['tenant_id'])
    contact_code = fields.Char('Kundnummer', related='tenant_id.contact_code', depends=['tenant_id'])
    national_registration_number = fields.Char('Personnummer', related='tenant_id.national_registration_number', depends=['tenant_id'])
    phone_number = fields.Char('Telefonnummer', related='tenant_id.phone_number', depends=['tenant_id'], readonly=False)
    email_address = fields.Char('E-postadress', related='tenant_id.email_address', depends=['tenant_id'], readonly=False)
    is_tenant = fields.Boolean('Är hyresgäst', related='tenant_id.is_tenant', depends=['tenant_id'])

    #   LEASE  ---------------------------------------------------------------------------------------------------------------------

    lease_id = fields.Many2one('maintenance.lease', string='Lease id', store=True)

    lease_name = fields.Char('Kontrakt', related='lease_id.name', depends=['lease_id'])
    lease_type = fields.Char('Typ av kontrakt', related='lease_id.lease_type', depends=['lease_id'])
    contract_date = fields.Date('Kontraktsdatum', related='lease_id.contract_date', depends=['lease_id'])
    lease_start_date = fields.Date('Kontrakt Startdatum', related='lease_id.lease_start_date', depends=['lease_id'])
    lease_end_date = fields.Date('Kontrakt Slutdatum', related='lease_id.lease_end_date', depends=['lease_id'])

    # Comes from Mimer.nu
    pet=fields.Char('Husdjur', store=True)
    call_between=fields.Char('Nås mellan', store=True)
    hearing_impaired=fields.Boolean('Hörselnedsättning', store=True)
    space_code=fields.Char('Utrymmeskod', store=True)
    space_caption=fields.Char('Utrymme', store=True, readonly=True)
    equipment_code=fields.Char('Utrustningskod', store=True, readonly=True)
    master_key=fields.Boolean('Huvudnyckel', store=True)

    # New fields
    priority_expanded=fields.Selection([('1', '1 dag'), ('5', '5 dagar'), ('7', '7 dagar'), ('10', '10 dagar'), ('14', '2 veckor')], string='Prioritet', store=True)
    due_date=fields.Date('Förfallodatum', compute='_compute_due_date', store=True)
    creation_origin=fields.Selection([('mimer-nu', 'Mimer.nu'), ('internal', 'Internt')], string='Skapad från', default='internal', store=True)

    # New fields for the form view only (not stored in the database)
    today_date = fields.Date(string='Today', compute='_compute_today_date', store=False)
    new_mimer_notification = fields.Boolean(
        string='New Mimer Message',
        compute='_compute_new_mimer_notification',
        store=False,
    )
    # This functions searches for notifications from Mimer.nu that are unread for the logged in user.
    @api.depends('message_ids.notification_ids.is_read', 'message_ids.notification_ids.notification_type')
    def _compute_new_mimer_notification(self):
        for record in self:
            message_ids = record.message_ids.ids

            unread_mimer_notifications = self.env['mail.notification'].search([
                ('mail_message_id', 'in', message_ids),
                ('res_partner_id', '=', self.env.user.partner_id.id),
                ('is_read', '=', False),
                ('notification_type', '=', 'inbox'),
                ('mail_message_id.author_id.user_ids.login', '=', 'admin' if is_local() else 'odoo@mimer.nu')
            ])

            record.new_mimer_notification = len(unread_mimer_notifications.ids) > 0

    # Domain for including users in the selected maintenance team
    maintenance_team_domain = fields.Binary(string="Maintenance team domain", compute="_compute_maintenance_team_domain")

    @api.depends('maintenance_team_id')
    def _compute_maintenance_team_domain(self):
        for record in self:
            if record.maintenance_team_id:
                ids = record.maintenance_team_id.member_ids.ids
                record.maintenance_team_domain = [("id", "in", ids)]

                if record.user_id.id not in ids:
                    record.user_id = False
            else:
                record.maintenance_team_domain = []

    @api.model
    def _compute_today_date(self):
        for record in self:
            record.today_date = fields.Date.context_today(self)


    @api.model
    def fields_get(self, allfields=None, attributes=None):
        # Hide filterable/searchable fields
        fields_to_hide = [
            'lease_number',
            'notice_given_by',
            'preferred_move_out_date',
            ]
        res = super().fields_get(allfields, attributes)
        for field in fields_to_hide:
            if res.get(field):
                res[field]['searchable'] = False
        return res

    @api.model
    def fetch_tenant_contact_data(self, thread_id):
        record = self.env['maintenance.request'].search([('id', '=', thread_id)])
        
        def is_valid(value):
            return value not in [None, False, '', 'redacted']
    
        return {
            'has_email': is_valid(record.tenant_id.email_address),
            'has_phone_number': is_valid(record.tenant_id.phone_number)
        }

    @api.model
    def fetch_property_data(self, search_by_number, search_type):
        onecore_auth = self.env['onecore.auth']
        base_url = self.env['ir.config_parameter'].get_param(
            'onecore_base_url', '')
        params = {'handler': search_type}
        url = f"{base_url}/workOrderData/{quote(str(search_by_number), safe='')}"

        try:
            response = onecore_auth.onecore_request('GET', url, params=params)
            response.raise_for_status()
            return response.json().get('content', {})
        except requests.HTTPError as http_err:
            _logger.error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            _logger.error(f"An error occurred: {err}")
        return None

    def update_form_options(self, search_by_number, search_type):
        _logger.info("Updating rental property options")
        data = self.fetch_property_data(search_by_number, search_type)
        self._delete_options()

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
                    'has_elevator': 'Ja' if property['property'].get('hasElevator') else 'Nej',
                    'wash_space': property['property'].get('washSpace'),
                    'estate_code': property['property'].get('estateCode'),
                    'estate': property['property'].get('estateName'),
                    'building_code': property['property'].get('buildingCode'),
                    'building': property['property'].get('building'),
                })
                if 'maintenanceUnits' in property and property['maintenanceUnits']:
                    for maintenance_unit in property['maintenanceUnits']:
                        if maintenance_unit['type'] == "Tvättstuga":
                            maintenance_unit_option = self.env['maintenance.maintenance.unit.option'].create({
                                'user_id': self.env.user.id,
                                'name': maintenance_unit['caption'],
                                'caption': maintenance_unit['caption'],
                                'type': maintenance_unit['type'],
                                'id': maintenance_unit['id'],
                                'code': maintenance_unit['code'],
                                'estate_code': maintenance_unit['estateCode'],
                                'rental_property_option_id': rental_property_option.id,
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
                        # Check if a tenant with the same contact_code already exists
                        existing_tenant = self.env['maintenance.tenant.option'].search([('contact_code', '=', tenant['contactCode'])], limit=1)

                        if not existing_tenant:
                            if tenant.get('firstName') and tenant.get('lastName'):
                                name = tenant['firstName'] + " " + tenant['lastName']
                            else:
                                name = tenant.get('fullName', '')

                            phone_number = next((item['phoneNumber'] for item in tenant.get('phoneNumbers') if item['isMainNumber'] == 1), None)
                            tenant_option = self.env['maintenance.tenant.option'].create({
                                'user_id': self.env.user.id,
                                'name': name,
                                'contact_code': tenant['contactCode'],
                                'contact_key': tenant['contactKey'],
                                'national_registration_number': tenant['nationalRegistrationNumber'],
                                'email_address': tenant.get('emailAddress'),
                                'phone_number': phone_number,
                                'is_tenant': tenant['isTenant'],
                            })
        else:
            _logger.info("No data found in response.")

    @api.onchange('search_by_number', 'search_type')
    def _compute_search(self):
        if self.search_by_number:
            for record in self:
                record.update_form_options(record.search_by_number, record.search_type)
                property_records = self.env['maintenance.rental.property.option'].search([('user_id', '=', self.env.user.id)])
                if property_records:
                    record.rental_property_option_id = property_records[0].id
                maintenance_unit_records = self.env['maintenance.maintenance.unit.option'].search([('user_id', '=', self.env.user.id)])
                if maintenance_unit_records:
                    record.maintenance_unit_option_id = maintenance_unit_records[0].id
                lease_records = self.env['maintenance.lease.option'].search([('user_id', '=', self.env.user.id)])
                if lease_records:
                    record.lease_option_id = lease_records[0].id
                tenant_records = self.env['maintenance.tenant.option'].search([('user_id', '=', self.env.user.id)])
                if tenant_records:
                    record.tenant_option_id = tenant_records[0].id
        else:
            self._delete_options()

    def _delete_options(self):
        self.env['maintenance.rental.property.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['maintenance.maintenance.unit.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['maintenance.lease.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['maintenance.tenant.option'].search([('user_id', '=', self.env.user.id)]).unlink()

    @api.depends('request_date', 'priority_expanded')
    def _compute_due_date(self):
        for record in self:
            if record.request_date and record.priority_expanded:
                record.due_date = fields.Date.add(record.request_date, days=int(record.priority_expanded))

    @api.onchange('rental_property_option_id')
    def _onchange_rental_property_option_id(self):
        if self.rental_property_option_id:
            for record in self:
                record.rental_property_id = record.rental_property_option_id.name
                record.address = record.rental_property_option_id.address
                record.property_type = record.rental_property_option_id.property_type
                record.code = record.rental_property_option_id.code
                record.type = record.rental_property_option_id.type
                record.area = record.rental_property_option_id.area
                record.entrance = record.rental_property_option_id.entrance
                record.floor = record.rental_property_option_id.floor
                record.has_elevator = record.rental_property_option_id.has_elevator
                record.wash_space = record.rental_property_option_id.wash_space
                record.estate_code = record.rental_property_option_id.estate_code
                record.estate = record.rental_property_option_id.estate
                record.building_code = record.rental_property_option_id.building_code
                record.building = record.rental_property_option_id.building

                lease_records = self.env['maintenance.lease.option'].search([('rental_property_option_id', '=', record.rental_property_option_id.id)])
                if lease_records:
                    record.lease_option_id = lease_records[0].id

    @api.onchange('maintenance_unit_option_id')
    def _onchange_maintenance_unit_option_id(self):
        if self.maintenance_unit_option_id:
            for record in self:
                record.maintenance_unit_id = record.maintenance_unit_option_id.name
                record.maintenance_unit_type = record.maintenance_unit_option_id.type
                record.maintenance_unit_code = record.maintenance_unit_option_id.code
                record.maintenance_unit_caption = record.maintenance_unit_option_id.caption

    @api.onchange('lease_option_id')
    def _onchange_lease_option_id(self):
        if self.lease_option_id:
            for record in self:
                record.lease_id = record.lease_option_id.name
                record.lease_type = record.lease_option_id.lease_type
                record.contract_date = record.lease_option_id.contract_date
                record.lease_start_date = record.lease_option_id.lease_start_date
                record.lease_end_date = record.lease_option_id.lease_end_date

                tenant_records = self.env['maintenance.tenant.option'].search([('id', '=', record.tenant_option_id.id)])
                if tenant_records:
                    record.tenant_option_id = tenant_records[0].id
                rental_property_records = self.env['maintenance.rental.property.option'].search([('id', '=', record.lease_option_id.rental_property_option_id.id)])
                if rental_property_records:
                    record.rental_property_option_id = rental_property_records[0].id

    @api.onchange('tenant_option_id')
    def _onchange_tenant_option_id(self):
        if self.tenant_option_id:
            for record in self:
                record.tenant_id = record.tenant_option_id.name
                record.tenant_name = record.tenant_option_id.name
                record.contact_code = record.tenant_option_id.contact_code
                record.national_registration_number = record.tenant_option_id.national_registration_number
                record.phone_number = record.tenant_option_id.phone_number
                record.email_address = record.tenant_option_id.email_address
                record.is_tenant = record.tenant_option_id.is_tenant

    def _resource_assigned(self):
        resource_allocated_stage = self.env['maintenance.stage'].search([
            ('name', '=', "Resurs tilldelad")
        ])
        if resource_allocated_stage:
            self.write({'stage_id': resource_allocated_stage.id})

    def _send_created_sms(self, phone_number):
        mail_message = self.env['mail.message']
        message = f"Hej {self.tenant_name}!\n\nTack för din serviceanmälan. Du kan följa, uppdatera och prata med oss om ditt ärende på Mina sidor."
        return mail_message._send_sms(phone_number, message)

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"Creating maintenance requests: {vals_list}")
        images = []
        for vals in vals_list:
            # SAVE RENTAL PROPERTY
            if vals.get('rental_property_option_id'):
                property_option_record = self.env['maintenance.rental.property.option'].search([('id', '=', vals.get('rental_property_option_id'))])
                new_property_record = self.env['maintenance.rental.property'].create({
                    'name': property_option_record.name,
                    'rental_property_id': property_option_record.name,
                    'property_type': property_option_record.property_type,
                    'address': property_option_record.address,
                    'code': property_option_record.code,
                    'type': property_option_record.type,
                    'area': property_option_record.area,
                    'entrance': property_option_record.entrance,
                    'floor': property_option_record.floor,
                    'has_elevator': property_option_record.has_elevator,
                    'wash_space': property_option_record.wash_space,
                    'estate_code': property_option_record.estate_code,
                    'estate': property_option_record.estate,
                    'building_code': property_option_record.building_code,
                    'building': property_option_record.building,
                })
                vals['rental_property_id'] = new_property_record.id

            # SAVE MAINTENANCE UNIT
            if vals.get('maintenance_unit_option_id'):
                maintenance_unit_option_record = self.env['maintenance.maintenance.unit.option'].search([('id', '=', vals.get('maintenance_unit_option_id'))])
                new_maintenance_unit_record = self.env['maintenance.maintenance.unit'].create({
                    'name': maintenance_unit_option_record.name,
                    'caption': maintenance_unit_option_record.caption,
                    'type': maintenance_unit_option_record.type,
                    'code': maintenance_unit_option_record.code,
                    'estate_code': maintenance_unit_option_record.estate_code,
                })
                vals['maintenance_unit_id'] = new_maintenance_unit_record.id

            # SAVE LEASE
            if vals.get('lease_option_id'):
                lease_option_record = self.env['maintenance.lease.option'].search([('id', '=', vals.get('lease_option_id'))])
                new_lease_record = self.env['maintenance.lease'].create({
                    'lease_id': lease_option_record.name,
                    'name': lease_option_record.name,
                    'lease_number': lease_option_record.lease_number,
                    'lease_type': lease_option_record.lease_type,
                    'lease_start_date': lease_option_record.lease_start_date,
                    'lease_end_date': lease_option_record.lease_end_date,
                    'contract_date': lease_option_record.contract_date,
                    'approval_date': lease_option_record.approval_date,
                })

                vals['lease_id'] = new_lease_record.id

            # SAVE TENANT
            if vals.get('tenant_option_id'):
                tenant_option_record = self.env['maintenance.tenant.option'].search([('id', '=', vals.get('tenant_option_id'))])
                new_tenant_record = self.env['maintenance.tenant'].create({
                    'name': tenant_option_record.name,
                    'contact_code': tenant_option_record.contact_code,
                    'contact_key': tenant_option_record.contact_key,
                    'national_registration_number': tenant_option_record.national_registration_number,
                    'email_address': tenant_option_record.email_address,
                    'phone_number': tenant_option_record.phone_number,
                    'is_tenant': tenant_option_record.is_tenant,
                })


                vals['tenant_id'] = new_tenant_record.id

            if 'images' in vals:
                images = vals.pop('images')

            # Fix for now to hide stuff specific for tvättstugeärenden
            if not vals.get('space_caption'):
                vals['space_caption'] = "Tvättstuga"

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
            if request.user_id and request.stage_id.name == "Väntar på handläggning":
                request._resource_assigned()
            if request.equipment_id and not request.maintenance_team_id:
                request.maintenance_team_id = request.equipment_id.maintenance_team_id
            if request.close_date and not request.stage_id.done:
                request.close_date = False
            if not request.close_date and request.stage_id.done:
                request.close_date = fields.Date.today()
            maintenance_requests.activity_update()

            if request.phone_number:
                request._send_created_sms(request.phone_number)


            # The below is  a Mimer added API-call to create errands in other app to test out a webhook, the api call to apps.mimer.nu is only to be used for testing.
            # Created errands will be created in a test app and can be viewed at https://apps.mimer.nu/version-test/odootest/'''


            # Only proceed if rental_property_option_id is present
            # if request.rental_property_option_id:
            #     ICP = self.env['ir.config_parameter'].sudo()
            #     token = ICP.get_param('x_webhook_bearer_token', default=None) #Note that this token needs to be added in the odoo interface, using developersettings.
            #     if not token:
            #         _logger.error("Bearer token is not set in system parameters.")
            #         return maintenance_requests

            #     webhook_url = "https://apps.mimer.nu/version-test/api/1.1/wf/createerrand"
            #     headers = {
            #         'Authorization': f'Bearer {token}',
            #         'Content-Type': 'application/json'
            #     }

            #      # Convert HTML to plain text
            #     description_text = html2plaintext(request.description) if request.description else ""

            #     data = {
            #         "rentalObjectId": request.rental_property_option_id.name,
            #         "title": request.name,
            #         "odooId": str(request.id),  # The unique Odoo ID
            #         "description": description_text,
            #         "state": request.stage_id.name,
            #     }
            #     try:
            #         response = requests.post(webhook_url, headers=headers, json=data)
            #         _logger.info(f"Webhook sent. Status Code: {response.status_code}, Response: {response.text}")
            #     except Exception as e:
            #         _logger.error(f"Failed to send webhook: {e}")
            # else:
            #     _logger.info(f"Webhook not sent. rental_property_option_id is missing for Maintenance Request ID: {request.id}")

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
        if vals.get('user_id') and self.stage_id.name == "Väntar på handläggning":
            self._resource_assigned()
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

        # for request in self:
        #     # Only proceed if rental_property_option_id is present
        #     if request.rental_property_option_id:
        #         ICP = request.env['ir.config_parameter'].sudo()
        #         token = ICP.get_param('x_webhook_bearer_token', default=None) #Note that this token needs to be added in the odoo interface, using developersettings.
        #         if not token:
        #             _logger.error("Bearer token is not set in system parameters.")
        #             continue  # Skip this iteration

        #         webhook_url = "https://apps.mimer.nu/version-test/api/1.1/wf/updateErrand"
        #         headers = {
        #             'Authorization': f'Bearer {token}',
        #             'Content-Type': 'application/json'
        #         }

        #         # Assuming you want to update the same fields as those you send when creating an errand
        #         description_text = html2plaintext(request.description) if request.description else ""
        #         data = {
        #             "odooId": str(request.id),
        #             "rentalObjectId": request.rental_property_option_id.name,
        #             "title": request.name,
        #             "description": description_text,
        #             "state": request.stage_id.name,
        #         }

        #         try:
        #             response = requests.post(webhook_url, headers=headers, json=data)
        #             _logger.info(f"Webhook for update sent. Status Code: {response.status_code}, Response: {response.text}")
        #         except Exception as e:
        #             _logger.error(f"Failed to send update webhook: {e}")

        return res


    #Mimer created webhook to delete errands from external testapp. https://apps.mimer.nu/version-test/odootest/
    # def unlink(self):
    #     ICP = self.env['ir.config_parameter'].sudo()
    #     token = ICP.get_param('x_webhook_bearer_token', default=None)
    #     if not token:
    #         _logger.error("Bearer token is not set in system parameters.")
    #     else:
    #         for request in self:
    #             if request.rental_property_option_id:
    #                 webhook_url = "https://apps.mimer.nu/version-test/api/1.1/wf/deleteerrand"
    #                 headers = {
    #                     'Authorization': f'Bearer {token}',
    #                     'Content-Type': 'application/json'
    #                 }
    #                 data = {"odooId": str(request.id)}
    #                 try:
    #                     response = requests.post(webhook_url, headers=headers, json=data)
    #                     if response.status_code != 200:
    #                         _logger.error(f"Webhook call failed: {response.text}")
    #                 except Exception as e:
    #                     _logger.error(f"Error calling webhook: {str(e)}")
    #             else:
    #                 _logger.info(f"Webhook not sent. rental_property_option_id is missing for Maintenance Request ID: {request.id}")

    #     return super().unlink()
