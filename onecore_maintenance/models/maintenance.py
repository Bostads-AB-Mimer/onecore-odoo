# -*- coding: utf-8 -*-

import ast
from dateutil.relativedelta import relativedelta
from urllib.parse import quote

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.osv import expression

#Mimerimports
from odoo import models, fields, api
from odoo.tools.mail import html2plaintext
import requests
import json
import logging

_logger = logging.getLogger(__name__)



class OnecoreMaintenanceStage(models.Model):
    """ Model for case stages. This models the main stages of a Maintenance Request management flow. """

    _name = 'onecore.maintenance.stage'
    _description = 'ONECore Maintenance Stage'
    _order = 'sequence, id'

    name = fields.Char('Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=20)
    fold = fields.Boolean('Folded in Maintenance Pipe')
    done = fields.Boolean('Request Done')


class OnecoreMaintenanceEquipmentCategory(models.Model):
    _name = 'onecore.maintenance.equipment.category'
    _inherit = ['mail.alias.mixin', 'mail.thread']
    _description = 'ONECore Maintenance Equipment Category'

    @api.depends('equipment_ids')
    def _compute_fold(self):
        # fix mutual dependency: 'fold' depends on 'equipment_count', which is
        # computed with a read_group(), which retrieves 'fold'!
        self.fold = False
        for category in self:
            category.fold = False if category.equipment_count else True

    name = fields.Char('Category Name', required=True, translate=True)
    company_id = fields.Many2one('res.company', string='Company',
        default=lambda self: self.env.company)
    technician_user_id = fields.Many2one('res.users', 'Responsible', tracking=True, default=lambda self: self.env.uid)
    color = fields.Integer('Color Index')
    note = fields.Html('Comments', translate=True)
    equipment_ids = fields.One2many('onecore.maintenance.equipment', 'category_id', string='Equipment', copy=False)
    equipment_count = fields.Integer(string="Equipment Count", compute='_compute_equipment_count')
    maintenance_ids = fields.One2many('onecore.maintenance.request', 'category_id', copy=False)
    maintenance_count = fields.Integer(string="Maintenance Count", compute='_compute_maintenance_count')
    maintenance_open_count = fields.Integer(string="Current Maintenance", compute='_compute_maintenance_count')
    alias_id = fields.Many2one(help="Email alias for this equipment category. New emails will automatically "
        "create a new equipment under this category.")
    fold = fields.Boolean(string='Folded in Maintenance Pipe', compute='_compute_fold', store=True)

    def _compute_equipment_count(self):
        equipment_data = self.env['onecore.maintenance.equipment']._read_group([('category_id', 'in', self.ids)], ['category_id'], ['__count'])
        mapped_data = {category.id: count for category, count in equipment_data}
        for category in self:
            category.equipment_count = mapped_data.get(category.id, 0)

    def _compute_maintenance_count(self):
        maintenance_data = self.env['maintenance.request']._read_group([('category_id', 'in', self.ids)], ['category_id', 'archive'], ['__count'])
        mapped_data = {(category.id, archive): count for category, archive, count in maintenance_data}
        for category in self:
            category.maintenance_open_count = mapped_data.get((category.id, False), 0)
            category.maintenance_count = category.maintenance_open_count + mapped_data.get((category.id, True), 0)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_contains_maintenance_requests(self):
        for category in self:
            if category.equipment_ids or category.maintenance_ids:
                raise UserError(_("You cannot delete an equipment category containing equipment or maintenance requests."))

    def _alias_get_creation_values(self):
        values = super(OnecoreMaintenanceEquipmentCategory, self)._alias_get_creation_values()
        values['alias_model_id'] = self.env['ir.model']._get('onecore.maintenance.request').id
        if self.id:
            values['alias_defaults'] = defaults = ast.literal_eval(self.alias_defaults or "{}")
            defaults['category_id'] = self.id
        return values


class OnecoreMaintenanceMixin(models.AbstractModel):
    _name = 'onecore.maintenance.mixin'
    _check_company_auto = True
    _description = 'ONECore Maintenance Maintained Item'

    company_id = fields.Many2one('res.company', string='Company',
        default=lambda self: self.env.company)
    effective_date = fields.Date('Effective Date', default=fields.Date.context_today, required=True, help="This date will be used to compute the Mean Time Between Failure.")
    maintenance_team_id = fields.Many2one('onecore.maintenance.team', string='Maintenance Team', compute='_compute_maintenance_team_id', store=True, readonly=False, check_company=True)
    technician_user_id = fields.Many2one('res.users', string='Technician', tracking=True)
    maintenance_ids = fields.One2many('onecore.maintenance.request')  # needs to be extended in order to specify inverse_name !
    maintenance_count = fields.Integer(compute='_compute_maintenance_count', string="Maintenance Count", store=True)
    maintenance_open_count = fields.Integer(compute='_compute_maintenance_count', string="Current Maintenance", store=True)
    expected_mtbf = fields.Integer(string='Expected MTBF', help='Expected Mean Time Between Failure')
    mtbf = fields.Integer(compute='_compute_maintenance_request', string='MTBF', help='Mean Time Between Failure, computed based on done corrective maintenances.')
    mttr = fields.Integer(compute='_compute_maintenance_request', string='MTTR', help='Mean Time To Repair')
    estimated_next_failure = fields.Date(compute='_compute_maintenance_request', string='Estimated time before next failure (in days)', help='Computed as Latest Failure Date + MTBF')
    latest_failure_date = fields.Date(compute='_compute_maintenance_request', string='Latest Failure Date')

    @api.depends('company_id')
    def _compute_maintenance_team_id(self):
        for record in self:
            if record.maintenance_team_id.company_id and record.maintenance_team_id.company_id.id != record.company_id.id:
                record.maintenance_team_id = False

    @api.depends('effective_date', 'maintenance_ids.stage_id', 'maintenance_ids.close_date', 'maintenance_ids.request_date')
    def _compute_maintenance_request(self):
        for record in self:
            maintenance_requests = record.maintenance_ids.filtered(lambda mr: mr.maintenance_type == 'corrective' and mr.stage_id.done)
            record.mttr = len(maintenance_requests) and (sum(int((request.close_date - request.request_date).days) for request in maintenance_requests) / len(maintenance_requests)) or 0
            record.latest_failure_date = max((request.request_date for request in maintenance_requests), default=False)
            record.mtbf = record.latest_failure_date and (record.latest_failure_date - record.effective_date).days / len(maintenance_requests) or 0
            record.estimated_next_failure = record.mtbf and record.latest_failure_date + relativedelta(days=record.mtbf) or False

    @api.depends('maintenance_ids.stage_id.done', 'maintenance_ids.archive')
    def _compute_maintenance_count(self):
        for record in self:
            record.maintenance_count = len(record.maintenance_ids)
            record.maintenance_open_count = len(record.maintenance_ids.filtered(lambda mr: not mr.stage_id.done and not mr.archive))


class OnecoreMaintenanceEquipment(models.Model):
    _name = 'onecore.maintenance.equipment'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'onecore.maintenance.mixin']
    _description = 'ONECore Maintenance Equipment'
    _check_company_auto = True

    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'owner_user_id' in init_values and self.owner_user_id:
            return self.env.ref('onecore_maintenance.mt_mat_assign')
        return super(OnecoreMaintenanceEquipment, self)._track_subtype(init_values)

    @api.depends('serial_no')
    def _compute_display_name(self):
        for record in self:
            if record.serial_no:
                record.display_name = record.name + '/' + record.serial_no
            else:
                record.display_name = record.name

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        query = None
        if name and operator not in expression.NEGATIVE_TERM_OPERATORS and operator != '=':
            query = self._search([('name', '=', name)] + domain, limit=limit, order=order)
        return query or super()._name_search(name, domain, operator, limit, order)

    name = fields.Char('Equipment Name', required=True, translate=True)
    active = fields.Boolean(default=True)
    owner_user_id = fields.Many2one('res.users', string='Owner', tracking=True)
    category_id = fields.Many2one('onecore.maintenance.equipment.category', string='Equipment Category',
                                  tracking=True, group_expand='_read_group_category_ids')
    partner_id = fields.Many2one('res.partner', string='Vendor', check_company=True)
    partner_ref = fields.Char('Vendor Reference')
    location = fields.Char('Location')
    model = fields.Char('Model')
    serial_no = fields.Char('Serial Number', copy=False)
    assign_date = fields.Date('Assigned Date', tracking=True)
    cost = fields.Float('Cost')
    note = fields.Html('Note')
    warranty_date = fields.Date('Warranty Expiration Date')
    color = fields.Integer('Color Index')
    scrap_date = fields.Date('Scrap Date')
    maintenance_ids = fields.One2many('onecore.maintenance.request', 'equipment_id')

    @api.onchange('category_id')
    def _onchange_category_id(self):
        self.technician_user_id = self.category_id.technician_user_id

    _sql_constraints = [
        ('serial_no', 'unique(serial_no)', "Another asset already exists with this serial number!"),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        equipments = super().create(vals_list)
        for equipment in equipments:
            if equipment.owner_user_id:
                equipment.message_subscribe(partner_ids=[equipment.owner_user_id.partner_id.id])
        return equipments

    def write(self, vals):
        if vals.get('owner_user_id'):
            self.message_subscribe(partner_ids=self.env['res.users'].browse(vals['owner_user_id']).partner_id.ids)
        return super(OnecoreMaintenanceEquipment, self).write(vals)

    @api.model
    def _read_group_category_ids(self, categories, domain, order):
        """ Read group customization in order to display all the categories in
            the kanban view, even if they are empty.
        """
        category_ids = categories._search([], order=order, access_rights_uid=SUPERUSER_ID)
        return categories.browse(category_ids)


class OnecoreMaintenanceRequest(models.Model):
    _name = 'onecore.maintenance.request'
    _inherit = ['mail.thread.cc', 'mail.activity.mixin']
    _description = 'ONECore Maintenance Request'
    _order = "id desc"
    _check_company_auto = True

    search_by_number = fields.Char('Search')
    search_type = fields.Selection([
        ('leaseId', 'Kontraktsnummer'),
        ('propertyId', 'Property ID'),
        ('pnr', 'Personnummer (12 siffror)'),
        ('phoneNumber', 'Telefonnummer (10 siffror)'),
    ], string='Search Type', default='leaseId', required=True)

    rental_property_id = fields.Many2one('onecore.maintenance.rental.property.option', compute='_compute_search', string='Property Id', store=True, readonly=False)
    address = fields.Char('Address', compute='_compute_rental_property', readonly=True)
    estate_code = fields.Char('Estate Code', compute='_compute_rental_property', readonly=True)
    estate_caption = fields.Char('Estate Caption', compute='_compute_rental_property', readonly=True)
    apartment_type = fields.Char('Type', compute='_compute_rental_property', readonly=True)
    bra = fields.Char('Bra', compute='_compute_rental_property', readonly=True)
    block_code = fields.Char('Block Code', compute='_compute_rental_property', readonly=True)

    lease = fields.Many2one('onecore.maintenance.lease.option', compute='_compute_search', string='Lease', store=True, readonly=False)
    lease_type = fields.Char('Lease Type', compute='_compute_lease', readonly=True)
    contract_date = fields.Date('Contract Date', compute='_compute_lease', readonly=True)
    lease_start_date = fields.Date('Lease Start Date', compute='_compute_lease', readonly=True)
    lease_end_date = fields.Date('Lease End Date', compute='_compute_lease', readonly=True)

    tenant = fields.Many2one('onecore.maintenance.tenant.option', compute='_compute_search', string='Tenant', store=True, readonly=False)
    national_registration_number = fields.Char('National Registration Number', compute='_compute_tenant', readonly=True)
    phone_number = fields.Char('Phone Number', compute='_compute_tenant', readonly=True)
    email_address = fields.Char('Email Address', compute='_compute_tenant', readonly=True)
    is_tenant = fields.Boolean('Is Tenant', compute='_compute_tenant', readonly=True)

    def fetch_property_data(self, search_by_number, search_type):
        base_url = self.env['ir.config_parameter'].get_param(
           'core_endpoint', '')
        bearer_token = self.env['ir.config_parameter'].get_param(
           'bearer_token', '')
        headers = {"Authorization": f"Bearer {bearer_token}"}
        params = {'typeOfNumber': search_type}
        url = f"{base_url}{quote(search_by_number, safe='')}"
        try:
            response = requests.get(url, headers=headers, params=params)
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
        _logger.info(f"Data: {data}")
        if data:
            for property in data:
                _logger.info(f"Creating rental property option: {property}")
                rental_property_option = self.env['onecore.maintenance.rental.property.option'].create({
                    'user_id': self.env.user.id,
                    'name': property['id'],
                    'property_address': property['address'],
                    'property_type': property['type'],
                    'property_size': property['size'],
                    'property_estate_code': property['estateCode'],
                    'property_estate_name': property['estateName'],
                    'property_block_code': property['blockCode'],
                })
                for lease in property['leases']:
                    _logger.info(f"Creating lease: {lease}")
                    lease_option = self.env['onecore.maintenance.lease.option'].create({
                        'user_id': self.env.user.id,
                        'name': lease['leaseId'],
                        'lease_number': lease['leaseNumber'],
                        'rental_property_option_id': rental_property_option.id,
                        'lease_type': lease['type'],
                        'lease_start_date': lease['leaseStartDate'],
                        'lease_end_date': lease['leaseEndDate'],
                        'contract_date': lease['contractDate'],
                        'approval_date': lease['approvalDate'],
                        # Add other fields as necessary
                    })
                    for tenant in lease['tenants']:
                        _logger.info(f"Creating tenant: {tenant}")
                        # Find the main phone number
                        phone_number = next((item['phoneNumber'] for item in tenant['phoneNumbers'] if item['isMainNumber'] == 1), None)
                        self.env['onecore.maintenance.tenant.option'].create({
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
        self.env['onecore.maintenance.rental.property.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['onecore.maintenance.lease.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        self.env['onecore.maintenance.tenant.option'].search([('user_id', '=', self.env.user.id)]).unlink()
        for record in self:
            if not record.search_by_number:
                record.search_by_number = False
                continue
            record.update_form_options(record.search_by_number, record.search_type)
            property_records = self.env['onecore.maintenance.rental.property.option'].search([('user_id', '=', self.env.user.id)])
            if property_records:
                record.rental_property_id = property_records[0].id
            lease_records = self.env['onecore.maintenance.lease.option'].search([('user_id', '=', self.env.user.id)])
            if lease_records:
                record.lease = lease_records[0].id
            tenant_records = self.env['onecore.maintenance.tenant.option'].search([('user_id', '=', self.env.user.id)])
            if tenant_records:
                record.tenant = tenant_records[0].id

    @api.depends('rental_property_id')
    def _compute_rental_property(self):
        for record in self:
            record.address = None
            record.estate_code = None
            record.estate_caption = None
            record.apartment_type = None
            record.bra = None
            record.block_code = None

            if record.rental_property_id:
                property = self.env['onecore.maintenance.rental.property.option'].search([('name', '=', record.rental_property_id.name)], limit=1)
                if property:
                    record.address = property.property_address
                    record.estate_code = property.property_estate_code
                    record.estate_caption = property.property_estate_name
                    record.apartment_type = property.property_type
                    record.bra = property.property_size
                    record.block_code = property.property_block_code

    @api.depends('lease')
    def _compute_lease(self):
        for record in self:
            record.lease_type = None
            record.contract_date = None
            record.lease_start_date = None
            record.lease_end_date = None

            if record.lease:
                lease = self.env['onecore.maintenance.lease.option'].search([('name', '=', record.lease.name)], limit=1)
                if lease:
                    record.lease_type = lease.lease_type
                    record.contract_date = lease.contract_date
                    record.lease_start_date = lease.lease_start_date
                    record.lease_end_date = lease.lease_end_date

    @api.depends('tenant')
    def _compute_tenant(self):
        for record in self:
            record.national_registration_number = None
            record.phone_number = None
            record.email_address = None
            record.is_tenant = None

            if record.tenant:
                tenant = self.env['onecore.maintenance.tenant.option'].search([('name', '=', record.tenant.name)], limit=1)
                if tenant:
                    record.national_registration_number = tenant.national_registration_number
                    record.phone_number = tenant.phone_number
                    record.email_address = tenant.email_address
                    record.is_tenant = tenant.is_tenant

    @api.returns('self')
    def _default_stage(self):
        return self.env['onecore.maintenance.stage'].search([], limit=1)

    def _creation_subtype(self):
        return self.env.ref('onecore_maintenance.mt_req_created')

    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'stage_id' in init_values:
            return self.env.ref('onecore_maintenance.mt_req_status')
        return super(OnecoreMaintenanceRequest, self)._track_subtype(init_values)

    def _get_default_team_id(self):
        MT = self.env['onecore.maintenance.team']
        team = MT.search([('company_id', '=', self.env.company.id)], limit=1)
        if not team:
            team = MT.search([], limit=1)
        return team.id

    name = fields.Char('Subjects', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    description = fields.Html('Description')
    request_date = fields.Date('Request Date', tracking=True, default=fields.Date.context_today,
                               help="Date requested for the maintenance to happen")
    owner_user_id = fields.Many2one('res.users', string='Created by User', default=lambda s: s.env.uid)
    category_id = fields.Many2one('onecore.maintenance.equipment.category', related='equipment_id.category_id', string='Category', store=True, readonly=True)
    equipment_id = fields.Many2one('onecore.maintenance.equipment', string='Equipment',
                                   ondelete='restrict', index=True, check_company=True)
    user_id = fields.Many2one('res.users', string='Technician', compute='_compute_user_id', store=True, readonly=False, tracking=True)
    stage_id = fields.Many2one('onecore.maintenance.stage', string='Stage', ondelete='restrict', tracking=True,
                               group_expand='_read_group_stage_ids', default=_default_stage, copy=False)
    priority = fields.Selection([('0', 'Very Low'), ('1', 'Low'), ('2', 'Normal'), ('3', 'High')], string='Priority')
    color = fields.Integer('Color Index')
    close_date = fields.Date('Close Date', help="Date the maintenance was finished. ")
    kanban_state = fields.Selection([('normal', 'In Progress'), ('blocked', 'Blocked'), ('done', 'Ready for next stage')],
                                    string='Kanban State', required=True, default='normal', tracking=True)
    # active = fields.Boolean(default=True, help="Set active to false to hide the maintenance request without deleting it.")
    archive = fields.Boolean(default=False, help="Set archive to true to hide the maintenance request without deleting it.")
    maintenance_type = fields.Selection([('corrective', 'Corrective'), ('preventive', 'Preventive')], string='Maintenance Type', default="corrective")
    schedule_date = fields.Datetime('Scheduled Date', help="Date the maintenance team plans the maintenance.  It should not differ much from the Request Date. ")
    maintenance_team_id = fields.Many2one('onecore.maintenance.team', string='Team', required=True, default=_get_default_team_id,
                                          compute='_compute_maintenance_team_id', store=True, readonly=False, check_company=True)
    duration = fields.Float(help="Duration in hours.")
    done = fields.Boolean(related='stage_id.done')
    instruction_type = fields.Selection([
        ('pdf', 'PDF'), ('google_slide', 'Google Slide'), ('text', 'Text')],
        string="Instruction", default="text"
    )
    instruction_pdf = fields.Binary('PDF')
    instruction_google_slide = fields.Char('Google Slide', help="Paste the url of your Google Slide. Make sure the access to the document is public.")
    instruction_text = fields.Html('Text')
    recurring_maintenance = fields.Boolean(string="Recurrent", compute='_compute_recurring_maintenance', store=True, readonly=False)
    repeat_interval = fields.Integer(string='Repeat Every', default=1)
    repeat_unit = fields.Selection([
        ('day', 'Days'),
        ('week', 'Weeks'),
        ('month', 'Months'),
        ('year', 'Years'),
    ], default='week')
    repeat_type = fields.Selection([
        ('forever', 'Forever'),
        ('until', 'Until'),
    ], default="forever", string="Until")
    repeat_until = fields.Date(string="End Date")

    def archive_equipment_request(self):
        self.write({'archive': True, 'recurring_maintenance': False})

    def reset_equipment_request(self):
        """ Reinsert the maintenance request into the maintenance pipe in the first stage"""
        first_stage_obj = self.env['onecore.maintenance.stage'].search([], order="sequence asc", limit=1)
        # self.write({'active': True, 'stage_id': first_stage_obj.id})
        self.write({'archive': False, 'stage_id': first_stage_obj.id})

    @api.depends('company_id', 'equipment_id')
    def _compute_maintenance_team_id(self):
        for request in self:
            if request.equipment_id and request.equipment_id.maintenance_team_id:
                request.maintenance_team_id = request.equipment_id.maintenance_team_id.id
            if request.maintenance_team_id.company_id and request.maintenance_team_id.company_id.id != request.company_id.id:
                request.maintenance_team_id = False

    @api.depends('company_id', 'equipment_id')
    def _compute_user_id(self):
        for request in self:
            if request.equipment_id:
                request.user_id = request.equipment_id.technician_user_id or request.equipment_id.category_id.technician_user_id
            if request.user_id and request.company_id.id not in request.user_id.company_ids.ids:
                request.user_id = False

    @api.depends('maintenance_type')
    def _compute_recurring_maintenance(self):
        for request in self:
            if request.maintenance_type != 'preventive':
                request.recurring_maintenance = False

    @api.model_create_multi
    def create(self, vals_list):
        maintenance_requests = super().create(vals_list)
        for request in maintenance_requests:
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


            # Only proceed if rental_property_id is present
            if request.rental_property_id:
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
                    "rentalObjectId": request.rental_property_id,
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
                _logger.info(f"Webhook not sent. rental_property_id is missing for Maintenance Request ID: {request.id}")

        return maintenance_requests

    def write(self, vals):
        if 'kanban_state' not in vals and 'stage_id' in vals:
            vals['kanban_state'] = 'normal'
        if 'stage_id' in vals and self.maintenance_type == 'preventive' and self.recurring_maintenance and self.env['onecore.maintenance.stage'].browse(vals['stage_id']).done:
            schedule_date = self.schedule_date or fields.Datetime.now()
            schedule_date += relativedelta(**{f"{self.repeat_unit}s": self.repeat_interval})
            if self.repeat_type == 'forever' or schedule_date.date() <= self.repeat_until:
                self.copy({'schedule_date': schedule_date})
        res = super(OnecoreMaintenanceRequest, self).write(vals)

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
            # Only proceed if rental_property_id is present
            if request.rental_property_id:
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
                    "rentalObjectId": request.rental_property_id,
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
                if request.rental_property_id:
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
                    _logger.info(f"Webhook not sent. rental_property_id is missing for Maintenance Request ID: {request.id}")

        return super(OnecoreMaintenanceRequest, self).unlink()


    def _need_new_activity(self, vals):
        return vals.get('equipment_id')

    def _get_activity_note(self):
        self.ensure_one()
        if self.equipment_id:
            return _('Request planned for %s', self.equipment_id._get_html_link())
        return False

    def activity_update(self):
        """ Update maintenance activities based on current record set state.
        It reschedule, unlink or create maintenance request activities. """
        self.filtered(lambda request: not request.schedule_date).activity_unlink(['maintenance.mail_act_maintenance_request'])
        for request in self.filtered(lambda request: request.schedule_date):
            date_dl = fields.Datetime.from_string(request.schedule_date).date()
            updated = request.activity_reschedule(
                ['maintenance.mail_act_maintenance_request'],
                date_deadline=date_dl,
                new_user_id=request.user_id.id or request.owner_user_id.id or self.env.uid)
            if not updated:
                note = self._get_activity_note()
                request.activity_schedule(
                    'maintenance.mail_act_maintenance_request',
                    fields.Datetime.from_string(request.schedule_date).date(),
                    note=note, user_id=request.user_id.id or request.owner_user_id.id or self.env.uid)

    def _add_followers(self):
        for request in self:
            partner_ids = (request.owner_user_id.partner_id + request.user_id.partner_id).ids
            request.message_subscribe(partner_ids=partner_ids)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        """ Read group customization in order to display all the stages in the
            kanban view, even if they are empty
        """
        stage_ids = stages._search([], order=order, access_rights_uid=SUPERUSER_ID)
        return stages.browse(stage_ids)


class OnecoreMaintenanceTeam(models.Model):
    _name = 'onecore.maintenance.team'
    _description = 'ONECore Maintenance Teams'

    name = fields.Char('Team Name', required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
        default=lambda self: self.env.company)
    member_ids = fields.Many2many(
        'res.users', 'onecore_maintenance_team_users_rel', string="Team Members",
        domain="[('company_ids', 'in', company_id)]")
    color = fields.Integer("Color Index", default=0)
    request_ids = fields.One2many('onecore.maintenance.request', 'maintenance_team_id', copy=False)
    equipment_ids = fields.One2many('onecore.maintenance.equipment', 'maintenance_team_id', copy=False)

    # For the dashboard only
    todo_request_ids = fields.One2many('onecore.maintenance.request', string="Requests", copy=False, compute='_compute_todo_requests')
    todo_request_count = fields.Integer(string="Number of Requests", compute='_compute_todo_requests')
    todo_request_count_date = fields.Integer(string="Number of Requests Scheduled", compute='_compute_todo_requests')
    todo_request_count_high_priority = fields.Integer(string="Number of Requests in High Priority", compute='_compute_todo_requests')
    todo_request_count_block = fields.Integer(string="Number of Requests Blocked", compute='_compute_todo_requests')
    todo_request_count_unscheduled = fields.Integer(string="Number of Requests Unscheduled", compute='_compute_todo_requests')

    @api.depends('request_ids.stage_id.done')
    def _compute_todo_requests(self):
        for team in self:
            team.todo_request_ids = self.env['onecore.maintenance.request'].search([('maintenance_team_id', '=', team.id), ('stage_id.done', '=', False), ('archive', '=', False)])
            data = self.env['onecore.maintenance.request']._read_group(
                [('maintenance_team_id', '=', team.id), ('stage_id.done', '=', False), ('archive', '=', False)],
                ['schedule_date:year', 'priority', 'kanban_state'],
                ['__count']
            )
            team.todo_request_count = sum(count for (_, _, _, count) in data)
            team.todo_request_count_date = sum(count for (schedule_date, _, _, count) in data if schedule_date)
            team.todo_request_count_high_priority = sum(count for (_, priority, _, count) in data if priority == 3)
            team.todo_request_count_block = sum(count for (_, _, kanban_state, count) in data if kanban_state == 'blocked')
            team.todo_request_count_unscheduled = team.todo_request_count - team.todo_request_count_date

    @api.depends('equipment_ids')
    def _compute_equipment(self):
        for team in self:
            team.equipment_count = len(team.equipment_ids)

class OnecoreMaintenanceRentalPropertyOption(models.Model):
    _name = 'onecore.maintenance.rental.property.option'
    _description = 'ONECore Rental Property Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    property_address = fields.Char('Address', required=True)
    property_type = fields.Char('Type', required=True)
    property_size = fields.Char('Size', required=True)
    property_estate_code = fields.Char('Estate Code', required=True)
    property_estate_name = fields.Char('Estate Name', required=True)
    property_block_code = fields.Char('Block Code', required=True)
    lease_ids = fields.One2many('onecore.maintenance.lease.option', 'rental_property_option_id', string='Leases')

class OnecoreMaintenanceLeaseOption(models.Model):
    _name = 'onecore.maintenance.lease.option'
    _description = 'ONECore Lease Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    lease_number = fields.Char('Lease Number', required=True)
    rental_property_option_id = fields.Many2one('onecore.maintenance.rental.property.option', string='Rental Property Option')
    lease_type = fields.Char('Type', required=True)
    lease_start_date = fields.Date('Lease Start Date', required=True)
    lease_end_date = fields.Date('Lease End Date')
    tenants = fields.One2many('onecore.maintenance.tenant.option', 'tenant_option_id', string='Tenants')
    notice_given_by = fields.Char('Notice Given By')
    notice_date = fields.Date('Notice Date')
    notice_time_tenant = fields.Integer('Notice Time Tenant')
    preferred_move_out_date = fields.Date('Preferred Move Out Date')
    termination_date = fields.Date('Termination Date')
    contract_date = fields.Date('Contract Date', required=True)
    last_debit_date = fields.Date('Last Debit Date')
    approval_date = fields.Date('Approval Date', required=True)

class OnecoreMaintenanceTenantOption(models.Model):
    _name = 'onecore.maintenance.tenant.option'
    _description = 'ONECore Tenant Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    contact_code = fields.Char('Contact Code', required=True)
    contact_key = fields.Char('Contact Key', required=True)
    national_registration_number = fields.Char('National Registration Number', required=True)
    phone_number = fields.Char('Phone Number', required=True)
    email_address = fields.Char('Email Address', required=True)
    is_tenant = fields.Boolean('Is Tenant', default=True)
    tenant_option_id = fields.Many2one('onecore.maintenance.lease.option', string='Lease Option')

