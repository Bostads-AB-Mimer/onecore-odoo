from collections.abc import Collection

from odoo import fields, models
from odoo.fields import Domain

from ..constants import SEARCH_TYPES
from ..services.ordering_department_service import clean_department


class SearchFieldsMixin(models.AbstractModel):
    """Mixin for search functionality fields."""

    _name = "maintenance.search.fields.mixin"
    _description = "Search Fields Mixin"

    # ============================================================================
    # PER-USER FILTERS — "mitt distrikt", "mina områden"
    # ============================================================================
    # Search-only booleans that resolve to a domain for the *current* user at
    # search time: which department they belong to (AD), which resource groups
    # they are a member of, which kvv areas they are the steward of. They make
    # the shipped favorites (data/ir_filters.xml) and the "Mitt distrikt" menu
    # one record each instead of one per district, and they need no per-user
    # configuration. Never stored, never computed: reading one gives False.
    #
    # Odoo 19 rewrites ('f', '=', True) to ('f', 'in', [True]) and both
    # ('f', '=', False) and ('f', '!=', True) to ('f', 'not in', [True]) before
    # the search method runs, so favorites can negate any of them.
    ordered_by_my_department = fields.Boolean(
        "Beställt av min avdelning",
        store=False,
        search="_search_ordered_by_my_department",
        help="Ärenden vars beställande avdelning är min avdelning enligt AD.",
    )
    in_my_district = fields.Boolean(
        "I mitt distrikt",
        store=False,
        search="_search_in_my_district",
        help="Ärenden i de distrikt (kostnadsställen) vars resursgrupper jag "
        "är medlem i, oavsett vilken resursgrupp ärendet ligger hos.",
    )
    at_my_teams = fields.Boolean(
        "Hos mina resursgrupper",
        store=False,
        search="_search_at_my_teams",
        help="Ärenden som ligger hos en resursgrupp jag är medlem i.",
    )
    in_my_kvv_areas = fields.Boolean(
        "I mina kvartersvärdsområden",
        store=False,
        search="_search_in_my_kvv_areas",
        help="Ärenden i de kvartersvärdsområden där jag är kvartersvärd "
        "enligt OneCore.",
    )
    is_performed = fields.Boolean(
        "Utförd",
        store=False,
        search="_search_is_performed",
        help="Ärenden i steget Utförd (klara men inte avslutade).",
    )
    # The one definition of "active" the search filters share (Aktiva,
    # Förfallna, Blockerat, Klart, Ej schemalagt): Utförd is not a done
    # stage, so "not done" alone would count it.
    is_active_status = fields.Boolean(
        "Aktiv",
        store=False,
        search="_search_is_active_status",
        help="Ärenden som varken är utförda eller avslutade. Väntar på "
        "handläggning och Återsänd räknas som aktiva.",
    )
    # The domain behind the resource group card's "Bevakning" numbers
    # (maintenance.team._ordered_domain). Not in the search view: nobody
    # types a team id.
    ordered_by_team_id = fields.Integer(
        "Beställt av resursgrupp",
        store=False,
        search="_search_ordered_by_team_id",
        help="Ärenden beställda av någon av resursgruppens medlemmars "
        "avdelningar.",
    )
    # The stage condition behind one number on the resource group card, e.g.
    # "queue:active" or "ordered:new_info" (maintenance.team._card_bucket_domain).
    # Lets the card's drilldown actions, which are XML records, filter on the
    # same definition the count uses.
    card_bucket = fields.Char(
        "Siffra på resursgruppskortet",
        store=False,
        search="_search_card_bucket",
    )

    # ------------------------------------------------------------------
    # What the current user is
    # ------------------------------------------------------------------
    # sudo: a contractor's env cannot read other users, teams' members or
    # the kvv-area master; the answers are about the current user only.
    def _my_department(self):
        """The current user's AD department in the form stamped on requests."""
        return clean_department(self.env.user.sudo().ad_office_location)

    def _my_teams(self):
        """Teams the current user is a member of, archived ones included.

        District teams are archived in prod until kvartersvärdarna start
        working in Odoo, yet they carry the cost_center_code that says which
        district the user belongs to.
        """
        return (
            self.env["maintenance.team"]
            .sudo()
            .with_context(active_test=False)
            .search([("member_ids", "in", [self.env.user.id])])
        )

    def _my_kvv_area_codes(self):
        """Codes of the kvv areas the current user is the steward of."""
        keycloak_id = self.env.user.sudo().oauth_uid
        if not keycloak_id:
            return []
        areas = (
            self.env["maintenance.kvv.area"]
            .sudo()
            .search([("responsible_keycloak_id", "=", keycloak_id)])
        )
        return [area.code for area in areas if area.code]

    # ------------------------------------------------------------------
    # Search methods
    # ------------------------------------------------------------------
    @staticmethod
    def _boolean_search_domain(operator, value, domain):
        """Map a boolean search condition onto ``domain`` (the True case).

        Handles the normalised ``in``/``not in`` the ORM sends (see the field
        comment above); anything else is left to the ORM, which then retries
        with the inverse operator and negates the result.
        """
        if operator not in ("in", "not in"):
            return NotImplemented
        wanted = {bool(v) for v in value}
        if not wanted:
            return Domain(operator != "in")
        if wanted == {True, False}:
            return Domain(operator == "in")
        positive = (operator == "in") == (True in wanted)
        return Domain(domain) if positive else ~Domain(domain)

    def _search_ordered_by_my_department(self, operator, value):
        department = self._my_department()
        domain = (
            Domain("ordering_department", "=", department)
            if department
            else Domain(False)
        )
        return self._boolean_search_domain(operator, value, domain)

    def _search_in_my_district(self, operator, value):
        codes = [
            team.cost_center_code for team in self._my_teams() if team.cost_center_code
        ]
        domain = Domain("cost_center_code", "in", codes) if codes else Domain(False)
        return self._boolean_search_domain(operator, value, domain)

    def _search_at_my_teams(self, operator, value):
        team_ids = self._my_teams().ids
        domain = (
            Domain("maintenance_team_id", "in", team_ids) if team_ids else Domain(False)
        )
        return self._boolean_search_domain(operator, value, domain)

    def _search_in_my_kvv_areas(self, operator, value):
        codes = self._my_kvv_area_codes()
        domain = Domain("kvv_area_code", "in", codes) if codes else Domain(False)
        return self._boolean_search_domain(operator, value, domain)

    def _search_is_performed(self, operator, value):
        # By xml-id, never by name: stage names are translated and renameable
        # stage_5 = Utförd, owned by us under the stock xml-id.
        stage = self.env.ref("maintenance.stage_5", raise_if_not_found=False)
        domain = Domain("stage_id", "=", stage.id) if stage else Domain(False)
        return self._boolean_search_domain(operator, value, domain)

    def _search_is_active_status(self, operator, value):
        domain = Domain("stage_id.done", "=", False)
        stage = self.env.ref("maintenance.stage_5", raise_if_not_found=False)
        if stage:
            domain &= Domain("stage_id", "!=", stage.id)
        return self._boolean_search_domain(operator, value, domain)

    def _search_card_bucket(self, operator, value):
        if operator in ("in", "not in") and not isinstance(value, str):
            keys = list(value)
        elif operator in ("=", "!="):
            keys = [value]
        else:
            return NotImplemented
        Team = self.env["maintenance.team"]
        domain = Domain.OR(Team._card_bucket_domain(key) for key in keys)
        return ~domain if operator in ("!=", "not in") else domain

    def _search_ordered_by_team_id(self, operator, value):
        """Requests ordered by any department a member of the team belongs to
        (see maintenance.team._member_departments)."""
        if operator in ("=", "in"):
            negate = False
        elif operator in ("!=", "not in"):
            negate = True
        else:
            return NotImplemented
        if isinstance(value, Collection) and not isinstance(value, str):
            team_ids = [int(v) for v in value if v]
        else:
            team_ids = [int(value)] if value else []
        # browse, not search: archived teams still have members with
        # departments.
        departments = self.env["maintenance.team"].browse(team_ids)._member_departments()
        domain = (
            Domain("ordering_department", "in", sorted(departments))
            if departments
            else Domain(False)
        )
        return ~domain if negate else domain

    # Search inputs
    search_value = fields.Char("Search", store=True)
    search_type = fields.Selection(
        SEARCH_TYPES,
        string="Search Type",
        default="pnr",
        required=True,
        store=True,
    )

    # Search option fields (populated by handlers, transient - not stored)
    property_option_id = fields.Many2one(
        "maintenance.property.option",
        string="Property Option Id",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    building_option_id = fields.Many2one(
        "maintenance.building.option",
        string="Building Option Id",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option",
        string="Rental Property Option Id",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    maintenance_unit_option_id = fields.Many2one(
        "maintenance.maintenance.unit.option",
        string="Maintenance Unit Option",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    tenant_option_id = fields.Many2one(
        "maintenance.tenant.option",
        string="Tenant",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    lease_option_id = fields.Many2one(
        "maintenance.lease.option",
        string="Lease",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    parking_space_option_id = fields.Many2one(
        "maintenance.parking.space.option",
        string="Parking Space",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    facility_option_id = fields.Many2one(
        "maintenance.facility.option",
        string="Facility",
        store=False,
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
