import datetime
from odoo import api, fields, models, _, exceptions
from markupsafe import Markup


import urllib.parse
import base64
import uuid
import requests
import json
import logging
import os
from ...onecore_api import core_api

_logger = logging.getLogger(__name__)


def is_local():
    return os.getenv("ENV") == "local"


validators = {
    "leaseId": lambda id: len(id) >= 8,
    "rentalObjectId": lambda id: len(id) >= 8,
    "contactCode": lambda code: len(code) >= 6,
    "pnr": lambda pnr: len(pnr) == 12 and str(pnr)[:2] in ["19", "20"],
    "buildingCode": lambda code: len(code) >= 6,
    "propertyName": lambda name: len(name) >= 3,
}


class OneCoreMaintenanceRequest(models.Model):
    _inherit = "maintenance.request"
    _order = "recently_added_tenant desc, request_date desc"

    uuid = fields.Char(
        string="UUID", default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )
    search_value = fields.Char("Search", store=False)
    search_type = fields.Selection(
        [
            ("leaseId", "Kontraktsnummer"),
            ("rentalObjectId", "Hyresobjekt"),
            ("contactCode", "Kundnummer"),
            ("pnr", "Personnummer (12 siffror)"),
            ("buildingCode", "Byggnadskod"),
            ("propertyName", "Fastighetsnamn"),
        ],
        string="Search Type",
        default="pnr",
        required=True,
        store=False,
    )

    property_option_id = fields.Many2one(
        "maintenance.property.option",
        compute="_compute_search",
        string="Property Option Id",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )

    building_option_id = fields.Many2one(
        "maintenance.building.option",
        compute="_compute_search",
        string="Building Option Id",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )

    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option",
        compute="_compute_search",
        string="Rental Property Option Id",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    maintenance_unit_option_id = fields.Many2one(
        "maintenance.maintenance.unit.option",
        compute="_compute_search",
        string="Maintenance Unit Option",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    tenant_option_id = fields.Many2one(
        "maintenance.tenant.option",
        compute="_compute_search",
        string="Tenant",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    lease_option_id = fields.Many2one(
        "maintenance.lease.option",
        compute="_compute_search",
        string="Lease",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    maintenance_request_category_id = fields.Many2one(
        "maintenance.request.category",
        string="Ärendekategori",
        required=True,
        store=True,
    )
    start_date = fields.Date("Startdatum", store=True)

    hidden_from_my_pages = fields.Boolean(
        "Dold från Mimer.nu", store=True, default=False
    )

    # PROPERTY

    property_id = fields.Many2one(
        "maintenance.property", store=True, string="Fastighet"
    )

    property_designation = fields.Char(
        "Fastighetsbeteckning",
        related="property_id.designation",
        depends=["property_id"],
    )

    #    BUILDING
    building_id = fields.Many2one("maintenance.building", store=True, string="Byggnad")

    building_name = fields.Char(
        "Byggnad",
        related="building_id.name",
        depends=["building_id"],
    )

    #    RENTAL PROPERTY  ---------------------------------------------------------------------------------------------------------------------

    rental_property_id = fields.Many2one(
        "maintenance.rental.property", store=True, string="Hyresobjekt"
    )

    rental_property_name = fields.Char(
        "Hyresobjekt Namn",
        related="rental_property_id.name",
        depends=["rental_property_id"],
    )
    address = fields.Char(
        "Adress", related="rental_property_id.address", depends=["rental_property_id"]
    )
    property_type = fields.Char(
        "Fastighetstyp",
        related="rental_property_id.property_type",
        depends=["rental_property_id"],
    )
    code = fields.Char(
        "Kod", related="rental_property_id.code", depends=["rental_property_id"]
    )
    type = fields.Char(
        "Typ", related="rental_property_id.type", depends=["rental_property_id"]
    )
    area = fields.Char(
        "Yta", related="rental_property_id.area", depends=["rental_property_id"]
    )
    entrance = fields.Char(
        "Ingång", related="rental_property_id.entrance", depends=["rental_property_id"]
    )
    floor = fields.Char(
        "Våning", related="rental_property_id.floor", depends=["rental_property_id"]
    )
    has_elevator = fields.Char(
        "Hiss",
        related="rental_property_id.has_elevator",
        depends=["rental_property_id"],
    )
    estate_code = fields.Char(
        "Fastighetskod",
        related="rental_property_id.estate_code",
        depends=["rental_property_id"],
    )
    estate = fields.Char(
        "Fastighet", related="rental_property_id.estate", depends=["rental_property_id"]
    )
    building_code = fields.Char(
        "Kvarterskod",
        related="rental_property_id.building_code",
        depends=["rental_property_id"],
    )
    building = fields.Char(
        "Kvarter", related="rental_property_id.building", depends=["rental_property_id"]
    )

    #    MAINTENANCE UNIT ---------------------------------------------------------------------------------------------------------------------

    maintenance_unit_id = fields.Many2one(
        "maintenance.maintenance.unit", string="Maintenance Unit ID", store=True
    )

    maintenance_unit_type = fields.Char(
        "Utrymmestyp",
        related="maintenance_unit_id.type",
        depends=["maintenance_unit_id"],
    )
    maintenance_unit_code = fields.Char(
        "Utrymmeskod",
        related="maintenance_unit_id.code",
        depends=["maintenance_unit_id"],
    )
    maintenance_unit_caption = fields.Char(
        "Utrymme",
        related="maintenance_unit_id.caption",
        depends=["maintenance_unit_id"],
    )

    #   TENANT  ---------------------------------------------------------------------------------------------------------------------

    tenant_id = fields.Many2one("maintenance.tenant", string="Hyresgäst ID", store=True)

    tenant_name = fields.Char("Namn", related="tenant_id.name", depends=["tenant_id"])
    contact_code = fields.Char(
        "Kundnummer", related="tenant_id.contact_code", depends=["tenant_id"]
    )
    national_registration_number = fields.Char(
        "Personnummer",
        related="tenant_id.national_registration_number",
        depends=["tenant_id"],
        groups="maintenance.group_equipment_manager",
    )
    phone_number = fields.Char(
        "Telefonnummer",
        related="tenant_id.phone_number",
        depends=["tenant_id"],
        readonly=False,
    )
    email_address = fields.Char(
        "E-postadress",
        related="tenant_id.email_address",
        depends=["tenant_id"],
        readonly=False,
    )
    is_tenant = fields.Boolean(
        "Är hyresgäst", related="tenant_id.is_tenant", depends=["tenant_id"]
    )

    #   LEASE  ---------------------------------------------------------------------------------------------------------------------

    lease_id = fields.Many2one("maintenance.lease", string="Lease id", store=True)

    lease_name = fields.Char("Kontrakt", related="lease_id.name", depends=["lease_id"])
    lease_type = fields.Char(
        "Typ av kontrakt", related="lease_id.lease_type", depends=["lease_id"]
    )
    contract_date = fields.Date(
        "Kontraktsdatum", related="lease_id.contract_date", depends=["lease_id"]
    )
    lease_start_date = fields.Date(
        "Kontrakt Startdatum", related="lease_id.lease_start_date", depends=["lease_id"]
    )
    lease_end_date = fields.Date(
        "Kontrakt Slutdatum", related="lease_id.lease_end_date", depends=["lease_id"]
    )

    # Comes from Mimer.nu
    pet = fields.Char("Husdjur", store=True)
    call_between = fields.Char("Nås mellan", store=True)
    hearing_impaired = fields.Boolean("Hörselnedsättning", store=True)
    space_code = fields.Char("Utrymmeskod", store=True)

    SPACES = [
        ("Byggnad", "Byggnad"),
        ("Fastighet", "Fastighet"),
        ("Lägenhet", "Lägenhet"),
        ("Tvättstuga", "Tvättstuga"),
        ("Uppgång", "Uppgång"),  # saknas typ i maintenance_unit
        ("Miljöbod", "Miljöbod"),
        ("Lekplats", "Lekplats"),
        ("Lokal", "Lokal"),
        ("Bilplats", "Bilplats"),
        ("Vind", "Vind"),  # saknas typ i maintenance_unit
        ("Källare", "Källare"),  # saknas typ i maintenance_unit
        ("Cykelförråd", "Cykelförråd"),  # saknas typ i maintenance_unit
        ("Övrigt", "Övrigt"),
        ("Gården/Utomhus", "Gården/Utomhus"),
    ]

    SORTED_SPACES = sorted(SPACES)

    space_caption = fields.Selection(
        selection=SORTED_SPACES,
        string="Utrymme",
        store=True,
        required=True,
    )
    equipment_code = fields.Char("Utrustningskod", store=True, readonly=True)
    master_key = fields.Boolean("Huvudnyckel", store=True)

    # New fields
    priority_expanded = fields.Selection(
        [
            ("1", "1 dag"),
            ("5", "5 dagar"),
            ("7", "7 dagar"),
            ("10", "10 dagar"),
            ("14", "2 veckor"),
            ("21", "3 veckor"),
            ("35", "5 veckor"),
            ("56", "8 veckor"),
        ],
        string="Prioritet",
        store=True,
    )
    due_date = fields.Date("Förfallodatum", compute="_compute_due_date", store=True)
    creation_origin = fields.Selection(
        [("mimer-nu", "Mimer.nu"), ("internal", "Internt")],
        string="Skapad från",
        default="internal",
        store=True,
    )

    # New fields for the form view only (not stored in the database)
    today_date = fields.Date(string="Today", compute="_compute_today_date", store=False)
    new_mimer_notification = fields.Boolean(
        string="New Mimer Message",
        compute="_compute_new_mimer_notification",
        store=False,
    )

    empty_tenant = fields.Boolean(
        string="No tenant", store=False, compute="_compute_empty_tenant"
    )

    recently_added_tenant = fields.Boolean(
        string="Recently added tenant", store=True, default=False
    )

    floor_plan_image = fields.Image(
        store=False, readonly=True, compute="_compute_floor_plan"
    )

    special_attention = fields.Boolean(
        string="Viktig kundinfo",
        related="tenant_id.special_attention",
        depends=["tenant_id"],
    )

    form_state = fields.Selection(
        [
            ("rental-property", "Bostad"),
            ("property", "Fastighet"),
            ("building", "Byggnad"),
        ],
        compute="_compute_form_state",
    )

    @api.depends(
        "property_id",
        "property_option_id",
        "building_id",
        "building_option_id",
    )
    def _compute_form_state(self):
        for record in self:
            if record.property_id or record.property_option_id:
                record.form_state = "property"
            elif record.building_id or record.building_option_id:
                record.form_state = "building"
            else:
                record.form_state = "rental-property"

    def get_core_api(self):
        return core_api.CoreApi(self.env)

    @api.depends("rental_property_id", "rental_property_option_id")
    def _compute_floor_plan(self):
        for record in self:
            id = (
                record.rental_property_id
                if record.rental_property_id
                else record.rental_property_option_id
            )

            if id and record.space_caption == "Lägenhet":
                url = f"https://pub.mimer.nu/bofaktablad/bofaktablad/{id.name}.jpg"
                response = requests.get(url)
                if response.status_code == 200:
                    record.floor_plan_image = base64.b64encode(response.content)
                else:
                    record.floor_plan_image = ""
            else:
                record.floor_plan_image = ""

    @api.depends("recently_added_tenant")
    def _compute_empty_tenant(self):
        for record in self:
            if record.lease_name and record.create_date or not record.create_date:
                record.empty_tenant = False
            else:
                record.empty_tenant = True

        if self.recently_added_tenant and self.tenant_id:
            # Check if the tenant was created more than two weeks ago
            if (datetime.datetime.now() - self.tenant_id.create_date).days > 14:
                for record in self:
                    record.recently_added_tenant = False
        else:
            for record in self:
                record.recently_added_tenant = False

        if self.rental_property_id and not self.lease_id:  # Empty tenant / lease
            data = self.fetch_property_data(
                "rentalObjectId", self.rental_property_id.name
            )
            if not data:
                return

            for property in data:
                if not property["leases"] or len(property["leases"]) == 0:
                    return  # No leases found in response.

                for lease in property["leases"]:

                    new_lease_record = self.env["maintenance.lease"].create(
                        {
                            "lease_id": lease["leaseId"],
                            "name": lease["leaseId"],
                            "lease_number": lease["leaseNumber"],
                            "lease_type": lease["type"],
                            "lease_start_date": lease["leaseStartDate"],
                            "lease_end_date": lease["lastDebitDate"],
                            "contract_date": lease["contractDate"],
                            "approval_date": lease["approvalDate"],
                        }
                    )

                    for record in self:
                        record.lease_id = new_lease_record.id

                    if new_lease_record:
                        for tenant in lease["tenants"]:
                            name = self._get_tenant_name(tenant)
                            phone_number = self._get_main_phone_number(tenant)

                            recently_added_tenant_record = self.env[
                                "maintenance.tenant"
                            ].create(
                                {
                                    "name": name,
                                    "contact_code": tenant["contactCode"],
                                    "contact_key": tenant["contactKey"],
                                    "national_registration_number": tenant[
                                        "nationalRegistrationNumber"
                                    ],
                                    "email_address": tenant.get("emailAddress"),
                                    "phone_number": phone_number,
                                    "is_tenant": tenant["isTenant"],
                                }
                            )

                            for record in self:
                                record.tenant_id = recently_added_tenant_record.id
                                record.recently_added_tenant = True
                                record.empty_tenant = False

    def _get_tenant_name(self, tenant):
        """
        Construct the tenant's name based on available information.
        """
        if tenant.get("firstName") and tenant.get("lastName"):
            return tenant["firstName"] + " " + tenant["lastName"]
        return tenant.get("fullName", "")

    def _get_main_phone_number(self, tenant):
        """
        Extract the main phone number from the tenant's phone numbers.
        """
        return next(
            (
                item["phoneNumber"]
                for item in tenant.get("phoneNumbers", [])
                if item["isMainNumber"] == 1
            ),
            None,
        )

    # This functions searches for notifications from Mimer.nu that are unread for the logged in user.
    @api.depends(
        "message_ids.notification_ids.is_read",
        "message_ids.notification_ids.notification_type",
    )
    def _compute_new_mimer_notification(self):
        for record in self:
            message_ids = record.message_ids.ids

            unread_mimer_notifications = self.env["mail.notification"].search(
                [
                    ("mail_message_id", "in", message_ids),
                    ("res_partner_id", "=", self.env.user.partner_id.id),
                    ("is_read", "=", False),
                    ("notification_type", "=", "inbox"),
                    (
                        "mail_message_id.author_id.user_ids.login",
                        "=",
                        "admin" if is_local() else "odoo@mimer.nu",
                    ),
                ]
            )

            record.new_mimer_notification = len(unread_mimer_notifications.ids) > 0

    # Domain for including users in the selected maintenance team
    maintenance_team_domain = fields.Binary(
        string="Maintenance team domain", compute="_compute_maintenance_team_domain"
    )

    # Whether some actions are restricted for external contractors
    restricted_external = fields.Boolean(
        string="Restricted external contractors", compute="_compute_restricted_external"
    )

    def _compute_restricted_external(self):
        if self.env.user.has_group(
            "onecore_maintenance_extension.group_external_contractor"
        ):
            restricted_stage_ids = self.env["maintenance.stage"].search(
                [("name", "in", ["Utförd", "Avslutad"])]
            )

            for record in self:
                record.restricted_external = record.stage_id in restricted_stage_ids
        else:
            self.restricted_external = False

    # Whether the user is an external contractor
    # Used by js components since user.hasGroup() can't always be used in js because it is async
    user_is_external_contractor = fields.Boolean(
        string="User is external contractor",
        compute="_compute_user_is_external_contractor",
    )

    def _compute_user_is_external_contractor(self):
        for record in self:
            record.user_is_external_contractor = self.env.user.has_group(
                "onecore_maintenance_extension.group_external_contractor"
            )

    @api.depends("maintenance_team_id")
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
            "lease_number",
            "notice_given_by",
            "preferred_move_out_date",
        ]
        res = super().fields_get(allfields, attributes)
        for field in fields_to_hide:
            if res.get(field):
                res[field]["searchable"] = False
        return res

    @api.model
    def fetch_tenant_contact_data(self, thread_id):
        record = self.env["maintenance.request"].search([("id", "=", thread_id)])

        def is_valid(value):
            return value not in [None, False, "", "redacted"]

        return {
            "has_email": is_valid(record.tenant_id.email_address),
            "has_phone_number": is_valid(record.tenant_id.phone_number),
        }

    @api.model
    def fetch_is_hidden_from_my_pages(self, thread_id):
        record = self.env["maintenance.request"].search([("id", "=", thread_id)])
        return {
            "hidden_from_my_pages": record.hidden_from_my_pages,
        }

    @api.model
    def is_user_external_contractor(self):
        is_external_contractor = self.env.user.has_group(
            "onecore_maintenance_extension.group_external_contractor"
        )
        return is_external_contractor

    def update_parking_space_form_options(self, work_order_data):

        print("updating parking space form options")
        for item in work_order_data:

            parking_space = item.get("parking_space")
            lease = item["lease"]

            print(f"Parking space: {parking_space}")
            print(f"Lease: {lease}")

            """
            parking_space_data = {
                'rentalId': '922-701-00-0009', 
                'companyCode': '001', 
                'companyName': 'BOSTADS AB MIMER', 
                'managementUnitCode': '61125', 
                'managementUnitName': '2: SKULTUNA 2', 
                'propertyCode': '10102', 
                'propertyName': 'SKULTUNABY 1:131', 
                'buildingCode': None, 
                'buildingName': None, 
                'parkingSpace': {
                    'propertyObjectId': '_1990IREALH69LQ', 
                    'code': '0009', 
                    'name': 'BANKVÄGEN 3', 
                    'parkingNumber': '922-701-00-0009', 
                    'parkingSpaceType': {
                        'code': 'PPLMEL', 
                        'name': 'Parkeringsplats med el'
                    }
                }, 
                'address': {
                    'streetAddress': 'Bankvägen 3', 
                    'streetAddress2': None, 
                    'postalCode': '726 31', 
                    'city': 'VÄSTERÅS'
                }
            }


            parking_space_option = self.env['maintenance.parking.space.option'].create(
                {
                    ...
                }
            )
            """

        return

    def update_rental_property_form_options(self, work_order_data):
        for item in work_order_data:
            property = item["rental_property"]
            lease = item["lease"]
            maintenance_units = item.get("maintenance_units", [])

            rental_property_option = self.env[
                "maintenance.rental.property.option"
            ].create(
                {
                    "user_id": self.env.user.id,
                    "name": property["rentalInformation"].get("rentalId"),
                    "address": property["name"],
                    "code": property["code"],
                    "property_type": property["type"].get("name"),
                    "area": property["areaSize"],
                    "entrance": property["entrance"],
                    "has_elevator": (
                        "Ja" if property["accessibility"].get("elevator") else "Nej"
                    ),
                    "estate_code": property["property"].get("code"),
                    "estate": property["property"].get("name"),
                    "building_code": property["building"].get("code"),
                    "building": property["building"].get("name"),
                }
            )

            lease_option = self.env["maintenance.lease.option"].create(
                {
                    "user_id": self.env.user.id,
                    "name": lease["leaseId"],
                    "lease_number": lease["leaseNumber"],
                    "rental_property_option_id": rental_property_option.id,
                    "lease_type": lease["type"],
                    "lease_start_date": lease["leaseStartDate"],
                    "lease_end_date": lease["lastDebitDate"],
                    "contract_date": lease["contractDate"],
                    "approval_date": lease["approvalDate"],
                }
            )

            for tenant in lease["tenants"]:
                # Check if a tenant with the same contact_code already exists
                existing_tenant = self.env["maintenance.tenant.option"].search(
                    [("contact_code", "=", tenant["contactCode"])], limit=1
                )

                if not existing_tenant:
                    name = self._get_tenant_name(tenant)
                    phone_number = self._get_main_phone_number(tenant)

                    self.env["maintenance.tenant.option"].create(
                        {
                            "user_id": self.env.user.id,
                            "name": name,
                            "contact_code": tenant["contactCode"],
                            "contact_key": tenant["contactKey"],
                            "national_registration_number": tenant.get(
                                "nationalRegistrationNumber"
                            ),
                            "email_address": tenant.get("emailAddress"),
                            "phone_number": phone_number,
                            "is_tenant": tenant["isTenant"],
                            "special_attention": tenant.get("specialAttention"),
                        }
                    )

            for maintenance_unit in maintenance_units:
                self.env["maintenance.maintenance.unit.option"].create(
                    {
                        "user_id": self.env.user.id,
                        "id": maintenance_unit["id"],
                        "name": maintenance_unit["caption"],
                        "caption": maintenance_unit["caption"],
                        "type": maintenance_unit["type"],
                        "code": maintenance_unit["code"],
                        "rental_property_option_id": rental_property_option.id,
                    }
                )

    def update_property_form_options(self, properties):
        for item in properties:
            property = item["property"]
            maintenance_units = item.get("maintenance_units", [])

            property_option = self.env["maintenance.property.option"].create(
                {
                    "user_id": self.env.user.id,
                    "designation": property["designation"],
                    "code": property["code"],
                }
            )

            for maintenance_unit in maintenance_units:
                maintenance_unit_option = self.env[
                    "maintenance.maintenance.unit.option"
                ].create(
                    {
                        "user_id": self.env.user.id,
                        "id": maintenance_unit["id"],
                        "name": maintenance_unit["caption"],
                        "caption": maintenance_unit["caption"],
                        "type": maintenance_unit["type"],
                        "code": maintenance_unit["code"],
                        "property_option_id": property_option.id,
                    }
                )

    def update_building_form_options(self, building):
        building_option = self.env["maintenance.building.option"].create(
            {
                "user_id": self.env.user.id,
                "name": building["name"],
                "code": building["code"],
            }
        )
        # TODO get maintenance units for building

    @api.onchange("search_value", "search_type", "space_caption")
    def _compute_search(self):
        if not self.search_value or not validators[self.search_type](self.search_value):
            self._delete_options()
            return

        for record in self:
            if self.search_type == "propertyName":
                properties = self.get_core_api().fetch_properties(
                    record.search_value, record.space_caption
                )

                if not properties:
                    _logger.info("No data found in response.")
                    raise exceptions.UserError(
                        _(
                            "Kunde inte hitta något resultat för %s",
                            record.search_value,
                        )
                    )

                record._delete_options()
                record.update_property_form_options(properties)

                property_records = self.env["maintenance.property.option"].search(
                    [("user_id", "=", self.env.user.id)]
                )

                if property_records:
                    record.property_option_id = property_records[0]

                maintenance_unit_records = self.env[
                    "maintenance.maintenance.unit.option"
                ].search(
                    [
                        ("user_id", "=", self.env.user.id),
                        ("property_option_id", "=", record.property_option_id.id),
                    ]
                )

                if maintenance_unit_records:
                    record.maintenance_unit_option_id = maintenance_unit_records[0]

            elif self.search_type == "buildingCode":
                building = self.get_core_api().fetch_building(record.search_value)

                if not building:
                    _logger.info("No data found in response.")
                    raise exceptions.UserError(
                        _(
                            "Kunde inte hitta något resultat för %s",
                            record.search_value,
                        )
                    )

                record._delete_options()
                record.update_building_form_options(building)

                building_records = self.env["maintenance.building.option"].search(
                    [("user_id", "=", self.env.user.id)]
                )

                if building_records:
                    record.building_option_id = building_records[0]
            else:
                work_order_data = self.get_core_api().fetch_form_data(
                    record.search_type, record.search_value, record.space_caption
                )

                if not work_order_data:
                    _logger.info("No data found in response.")
                    raise exceptions.UserError(
                        _(
                            "Kunde inte hitta något resultat för %s",
                            record.search_value,
                        )
                    )

                record._delete_options()

                if self.space_caption == "Bilplats":
                    record.update_parking_space_form_options(work_order_data)
                else:
                    record.update_rental_property_form_options(work_order_data)

                property_records = self.env[
                    "maintenance.rental.property.option"
                ].search([("user_id", "=", self.env.user.id)])
                if property_records:
                    record.rental_property_option_id = property_records[0].id

                maintenance_unit_records = self.env[
                    "maintenance.maintenance.unit.option"
                ].search([("user_id", "=", self.env.user.id)])
                if maintenance_unit_records:
                    record.maintenance_unit_option_id = maintenance_unit_records[0].id

                lease_records = self.env["maintenance.lease.option"].search(
                    [("user_id", "=", self.env.user.id)]
                )
                if lease_records:
                    record.lease_option_id = lease_records[0].id

                parking_space_records = self.env[
                    "maintenance.parking.space.option"
                ].search([("user_id", "=", self.env.user.id)])
                if parking_space_records:
                    record.parking_space_option_id = parking_space_records[0].id

                tenant_records = self.env["maintenance.tenant.option"].search(
                    [("user_id", "=", self.env.user.id)]
                )
                if tenant_records:
                    record.tenant_option_id = tenant_records[0].id

    def _delete_options(self):
        self.env["maintenance.property.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.building.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.rental.property.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.maintenance.unit.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.parking.space.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.tenant.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()

    @api.depends("request_date", "start_date", "priority_expanded")
    def _compute_due_date(self):
        for record in self:
            base_date = record.start_date if record.start_date else record.request_date

            if base_date and record.priority_expanded:
                record.due_date = fields.Date.add(
                    base_date, days=int(record.priority_expanded)
                )

    @api.onchange("property_option_id")
    def _onchange_property_option_id(self):
        if self.property_option_id:
            for record in self:
                record.property_id = record.property_option_id.id
                record.property_designation = record.property_option_id.designation
                record.maintenance_unit_option_id = False

    @api.onchange("rental_property_option_id")
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
                record.estate_code = record.rental_property_option_id.estate_code
                record.estate = record.rental_property_option_id.estate
                record.building_code = record.rental_property_option_id.building_code
                record.building = record.rental_property_option_id.building

                lease_records = self.env["maintenance.lease.option"].search(
                    [
                        (
                            "rental_property_option_id",
                            "=",
                            record.rental_property_option_id.id,
                        )
                    ]
                )
                if lease_records:
                    record.lease_option_id = lease_records[0].id

    @api.onchange("maintenance_unit_option_id")
    def _onchange_maintenance_unit_option_id(self):
        if self.maintenance_unit_option_id:
            for record in self:
                record.maintenance_unit_id = record.maintenance_unit_option_id.name
                record.maintenance_unit_type = record.maintenance_unit_option_id.type
                record.maintenance_unit_code = record.maintenance_unit_option_id.code
                record.maintenance_unit_caption = (
                    record.maintenance_unit_option_id.caption
                )

    @api.onchange("lease_option_id")
    def _onchange_lease_option_id(self):
        if self.lease_option_id:
            for record in self:
                record.lease_id = record.lease_option_id.name
                record.lease_type = record.lease_option_id.lease_type
                record.contract_date = record.lease_option_id.contract_date
                record.lease_start_date = record.lease_option_id.lease_start_date
                record.lease_end_date = record.lease_option_id.lease_end_date

                tenant_records = self.env["maintenance.tenant.option"].search(
                    [("id", "=", record.tenant_option_id.id)]
                )
                if tenant_records:
                    record.tenant_option_id = tenant_records[0].id
                rental_property_records = self.env[
                    "maintenance.rental.property.option"
                ].search(
                    [("id", "=", record.lease_option_id.rental_property_option_id.id)]
                )
                if rental_property_records:
                    record.rental_property_option_id = rental_property_records[0].id

    @api.onchange("tenant_option_id")
    def _onchange_tenant_option_id(self):
        if self.tenant_option_id:
            for record in self:
                record.tenant_id = record.tenant_option_id.name
                record.tenant_name = record.tenant_option_id.name
                record.contact_code = record.tenant_option_id.contact_code
                record.national_registration_number = (
                    record.tenant_option_id.national_registration_number
                )
                record.phone_number = record.tenant_option_id.phone_number
                record.email_address = record.tenant_option_id.email_address
                record.is_tenant = record.tenant_option_id.is_tenant
                record.special_attention = record.tenant_option_id.special_attention

    def _send_created_sms(self, phone_number):
        mail_message = self.env["mail.message"]
        message = f"Hej {self.tenant_name}!\n\nTack för din serviceanmälan. Du kan följa, uppdatera och prata med oss om ditt ärende på Mina sidor."
        return mail_message._send_sms(phone_number, message)

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"Creating maintenance requests: {vals_list}")
        images = []

        # Remove images from vals_list before saving the requests
        for vals in vals_list:
            if "images" in vals:
                images.append(vals.pop("images"))

        maintenance_requests = super(
            OneCoreMaintenanceRequest, self.with_context(creating_records=True)
        ).create(vals_list)

        for idx, vals in enumerate(vals_list):
            maintenance_request = maintenance_requests[idx]
            # SAVE PROPERTY
            if vals.get("property_option_id"):
                property_option_record = self.env["maintenance.property.option"].search(
                    [("id", "=", vals.get("property_option_id"))]
                )
                new_property_record = self.env["maintenance.property"].create(
                    {
                        "designation": property_option_record.designation,
                        "code": property_option_record.code,
                        "maintenance_request_id": maintenance_request.id,
                    }
                )

                maintenance_request.write({"property_id": new_property_record.id})

            # SAVE BUILDING
            if vals.get("building_option_id"):
                building_option_record = self.env["maintenance.building.option"].search(
                    [("id", "=", vals.get("building_option_id"))]
                )
                new_building_record = self.env["maintenance.building"].create(
                    {
                        "name": building_option_record.name,
                        "code": building_option_record.code,
                        "maintenance_request_id": maintenance_request.id,
                    }
                )

                maintenance_request.write({"building_id": new_building_record.id})

            # SAVE RENTAL PROPERTY
            if vals.get("rental_property_option_id"):
                property_option_record = self.env[
                    "maintenance.rental.property.option"
                ].search([("id", "=", vals.get("rental_property_option_id"))])
                new_property_record = self.env["maintenance.rental.property"].create(
                    {
                        "name": property_option_record.name,
                        "rental_property_id": property_option_record.name,
                        "property_type": property_option_record.property_type,
                        "address": property_option_record.address,
                        "code": property_option_record.code,
                        "type": property_option_record.type,
                        "area": property_option_record.area,
                        "entrance": property_option_record.entrance,
                        "floor": property_option_record.floor,
                        "has_elevator": property_option_record.has_elevator,
                        "estate_code": property_option_record.estate_code,
                        "estate": property_option_record.estate,
                        "building_code": property_option_record.building_code,
                        "building": property_option_record.building,
                        "maintenance_request_id": maintenance_request.id,
                    }
                )

                maintenance_request.write(
                    {"rental_property_id": new_property_record.id}
                )

            # SAVE MAINTENANCE UNIT
            if vals.get("maintenance_unit_option_id"):
                maintenance_unit_option_record = self.env[
                    "maintenance.maintenance.unit.option"
                ].search([("id", "=", vals.get("maintenance_unit_option_id"))])
                new_maintenance_unit_record = self.env[
                    "maintenance.maintenance.unit"
                ].create(
                    {
                        "name": maintenance_unit_option_record.name,
                        "caption": maintenance_unit_option_record.caption,
                        "type": maintenance_unit_option_record.type,
                        "code": maintenance_unit_option_record.code,
                        "maintenance_request_id": maintenance_request.id,
                    }
                )

                maintenance_request.write(
                    {"maintenance_unit_id": new_maintenance_unit_record.id}
                )

            # SAVE LEASE
            if vals.get("lease_option_id"):
                lease_option_record = self.env["maintenance.lease.option"].search(
                    [("id", "=", vals.get("lease_option_id"))]
                )
                new_lease_record = self.env["maintenance.lease"].create(
                    {
                        "lease_id": lease_option_record.name,
                        "name": lease_option_record.name,
                        "lease_number": lease_option_record.lease_number,
                        "lease_type": lease_option_record.lease_type,
                        "lease_start_date": lease_option_record.lease_start_date,
                        "lease_end_date": lease_option_record.lease_end_date,
                        "contract_date": lease_option_record.contract_date,
                        "approval_date": lease_option_record.approval_date,
                        "maintenance_request_id": maintenance_request.id,
                    }
                )

                maintenance_request.write({"lease_id": new_lease_record.id})

            # SAVE TENANT
            if vals.get("tenant_option_id"):
                tenant_option_record = self.env["maintenance.tenant.option"].search(
                    [("id", "=", vals.get("tenant_option_id"))]
                )
                new_tenant_record = self.env["maintenance.tenant"].create(
                    {
                        "name": tenant_option_record.name,
                        "contact_code": tenant_option_record.contact_code,
                        "contact_key": tenant_option_record.contact_key,
                        "national_registration_number": tenant_option_record.national_registration_number,
                        "email_address": tenant_option_record.email_address,
                        "phone_number": tenant_option_record.phone_number,
                        "is_tenant": tenant_option_record.is_tenant,
                        "special_attention": tenant_option_record.special_attention,
                        "maintenance_request_id": maintenance_request.id,
                    }
                )

                maintenance_request.write({"tenant_id": new_tenant_record.id})

            # Fix for now to hide stuff specific for tvättstugeärenden
            if not vals.get("space_caption"):
                vals["space_caption"] = "Tvättstuga"

        for idx, request in enumerate(maintenance_requests):
            if len(images) > 0:
                request_images = images[idx]
                for image in request_images:
                    file_data = base64.b64decode(image["Base64String"])
                    attachment = self.env["ir.attachment"].create(
                        {
                            "name": image["Filename"],
                            "type": "binary",
                            "datas": base64.b64encode(file_data),
                            "res_model": "maintenance.request",
                            "res_id": request.id,
                            "mimetype": "application/octet-stream",
                        }
                    )

            if request.owner_user_id or request.user_id:
                request._add_followers()

            if request.user_id and request.stage_id.name == "Väntar på handläggning":
                resource_allocated_stage = self.env["maintenance.stage"].search(
                    [("name", "=", "Resurs tilldelad")]
                )
                if resource_allocated_stage:
                    request.stage_id = resource_allocated_stage.id

            if request.equipment_id and not request.maintenance_team_id:
                request.maintenance_team_id = request.equipment_id.maintenance_team_id
            if request.close_date and not request.stage_id.done:
                request.close_date = False
            if not request.close_date and request.stage_id.done:
                request.close_date = fields.Date.today()
            maintenance_requests.activity_update()

            if request.phone_number and not request.hidden_from_my_pages:
                request._send_created_sms(request.phone_number)

        return maintenance_requests

    def open_time_report(self):
        """
        Open the time report application in a new window.
        The function passes the estate code as a URL parameter 'p'
        and the maintenance request ID as a URL parameter 'od'.
        """
        self.ensure_one()
        # Get estate code from either rental property or maintenance unit
        estate_code = False
        if self.rental_property_id and self.rental_property_id.estate_code:
            estate_code = self.rental_property_id.estate_code
        elif self.maintenance_unit_id and self.maintenance_unit_id.estate_code:
            estate_code = self.maintenance_unit_id.estate_code

        # Get the base URL from system parameters
        base_url = self.env["ir.config_parameter"].get_param(
            "time_report_base_url",
            "https://apps.mimer.nu/version-test/tidsrapportering/",
        )

        # Construct the URL with both estate code and maintenance request ID
        url = base_url
        params = {"od": self.id}
        if estate_code:
            params["p"] = estate_code
        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "self",  # Opens in a new tab/window
        }

    def write(self, vals):
        if "stage_id" in vals:
            if self.env.user.has_group(
                "onecore_maintenance_extension.group_external_contractor"
            ):
                if self.stage_id.name == "Utförd":
                    raise exceptions.UserError(
                        "Du har inte behörighet att flytta detta ärende från Utförd"
                    )
                if self.stage_id.name == "Avslutad":
                    raise exceptions.UserError(
                        "Du har inte behörighet att flytta detta ärende från Avslutad"
                    )

                restricted_stages = self.env["maintenance.stage"].search(
                    [("name", "=", "Avslutad")]
                )
                if vals["stage_id"] in restricted_stages.ids:
                    raise exceptions.UserError(
                        "Du har inte behörighet att flytta detta ärende till Avslutad"
                    )

            if not self.user_id:
                allowed_stages = self.env["maintenance.stage"].search(
                    [("name", "in", ["Väntar på handläggning", "Avslutad"])]
                )
                if vals["stage_id"] not in allowed_stages.ids:
                    raise exceptions.UserError(
                        "Ingen resurs är tilldelad. Vänligen välj en resurs."
                    )

        if vals.get("user_id") and self.stage_id.name == "Väntar på handläggning":
            resource_allocated_stage = self.env["maintenance.stage"].search(
                [("name", "=", "Resurs tilldelad")]
            )
            vals.update({"stage_id": resource_allocated_stage.id})
        elif vals.get("user_id") is False and self.stage_id.name == "Resurs tilldelad":
            initial_stage = self.env["maintenance.stage"].search(
                [("name", "=", "Väntar på handläggning")]
            )
            vals.update({"stage_id": initial_stage.id})

        # Skip change tracking during record creation
        if self.env.context.get("creating_records"):
            return super().write(vals)

        changes_by_record = self._track_field_changes(vals)

        result = super().write(vals)

        self._post_change_notifications(changes_by_record)

        return result

    def _track_field_changes(self, vals):
        skip_fields = {
            "message_main_attachment_id",
            "message_ids",
            "activity_ids",
            "website_message_ids",
            "__last_update",
            "display_name",
            "stage_id",
        }

        filtered_vals = {k: v for k, v in vals.items() if k not in skip_fields}

        if not filtered_vals:
            return {}

        changes_by_record = {}
        for record in self:
            changes = []
            for field, new_value in filtered_vals.items():
                old_value = record[field]
                if old_value == new_value:
                    continue

                field_obj = record._fields[field]
                field_label = field_obj.get_description(self.env)["string"]

                change_text = self._format_field_change(
                    field_obj, old_value, new_value, field_label
                )
                if change_text:
                    changes.append(change_text)

            changes_by_record[record.id] = changes

        return changes_by_record

    def _format_field_change(self, field_obj, old_value, new_value, field_label):
        if field_obj.name == "description":
            return f"<strong>{field_label}:</strong> Uppdaterad"

        if isinstance(field_obj, fields.Many2one):
            old_display = old_value.display_name if old_value else "Inte valt"
            if new_value:
                new_record = self.env[field_obj.comodel_name].browse(new_value)
                new_display = (
                    new_record.display_name if new_record.exists() else "Inte valt"
                )
            else:
                new_display = "Inte valt"

            return (
                f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"
                if old_display != new_display
                else None
            )

        elif isinstance(field_obj, fields.Selection):
            selection = field_obj.selection
            if callable(selection):
                selection = selection(self)

            old_display = next(
                (label for value, label in selection if value == old_value),
                "Inte satt" if old_value in [False, None, ""] else str(old_value),
            )
            new_display = next(
                (label for value, label in selection if value == new_value),
                "Inte satt" if new_value in [False, None, ""] else str(new_value),
            )

            return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

        elif isinstance(field_obj, fields.Boolean):
            old_display = "Ja" if old_value else "Nej"
            new_display = "Ja" if new_value else "Nej"
            return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

        elif isinstance(field_obj, (fields.Date, fields.Datetime)):
            old_display = old_value.strftime("%Y-%m-%d") if old_value else "Inte satt"

            if isinstance(new_value, str):
                try:
                    new_date = (
                        fields.Date.from_string(new_value)
                        if new_value != "False"
                        else None
                    )
                    new_display = (
                        new_date.strftime("%Y-%m-%d") if new_date else "Inte satt"
                    )
                except:
                    new_display = str(new_value) if new_value else "Inte satt"
            else:
                new_display = (
                    new_value.strftime("%Y-%m-%d") if new_value else "Inte satt"
                )

            return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

        else:
            old_display = str(old_value) if old_value else "Inte satt"
            new_display = str(new_value) if new_value else "Inte satt"
            return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

    def _post_change_notifications(self, changes_by_record):
        for record in self:
            if record.id in changes_by_record and changes_by_record[record.id]:
                html_content = (
                    "<div>" + "<br/>".join(changes_by_record[record.id]) + "</div>"
                )
                record.message_post(
                    body=Markup(html_content),
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )
