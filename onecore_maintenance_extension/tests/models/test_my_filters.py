"""Tests for the per-user search fields, the shipped
favorites built on them and the "Mitt distrikt" menu.

Each field is a search-only boolean on maintenance.request that resolves to
a domain for the *current* user: their AD department, the resource groups
they are a member of, the kvv areas they are the steward of. Covered here
for three profiles — a district user, a Kundcenter user and a user with no
department, no team and no Keycloak id — plus both polarities, since the
favorites negate them. The favorites are then evaluated the way the web
client does (domain, group-by, sort) for all three profiles.
"""
import json

from lxml import etree
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
)


class MyFiltersFixture:
    """Two districts, three user profiles, five requests."""

    def setUp(self):
        super().setUp()
        Request = self.env["maintenance.request"]

        self.vast_team = create_maintenance_team(
            self.env, name="Distrikt Väst (test)", cost_center_code="61140"
        )
        self.ost_team = create_maintenance_team(
            self.env, name="Distrikt Öst (test)", cost_center_code="61120"
        )

        # A kvartersvärd in Distrikt Väst: department from AD, member of the
        # district's resource group, steward of one kvv area in OneCore.
        self.district_user = create_internal_user(
            self.env,
            ad_office_location="Distrikt Väst",
            oauth_uid="keycloak-sub-vast",
        )
        self.vast_team.member_ids = [(4, self.district_user.id)]
        # Kundcenter: a department, but no resource group and no kvv area.
        self.kundcenter_user = create_internal_user(
            self.env, ad_office_location="Kundcenter"
        )
        # A service account or a consultant: nothing at all.
        self.blank_user = create_internal_user(self.env)

        KvvArea = self.env["maintenance.kvv.area"]
        self.vast_area = KvvArea.create(
            {
                "code": "61141",
                "name": "Väst 1",
                "cost_center_code": "61140",
                "responsible_keycloak_id": "keycloak-sub-vast",
            }
        )
        self.ost_area = KvvArea.create(
            {
                "code": "61121",
                "name": "Öst 1",
                "cost_center_code": "61120",
                "responsible_keycloak_id": "keycloak-sub-someone-else",
            }
        )

        # Ordered by Distrikt Väst, sitting with Distrikt Väst, in its area.
        self.own_here = self._request(
            self.district_user, self.vast_team, "61140", "61141"
        )
        # Ordered by Distrikt Väst, sitting with Distrikt Öst, in Öst's area:
        # the "beställt hos andra" case.
        self.own_elsewhere = self._request(
            self.district_user, self.ost_team, "61120", "61121"
        )
        # Ordered by Kundcenter, sitting with Distrikt Väst, in Väst's area:
        # the "i mitt distrikt, beställt av andra" case.
        self.other_here = self._request(
            self.kundcenter_user, self.vast_team, "61140", "61141"
        )
        # No department, no team, no codes.
        self.blank = self._request(self.blank_user)
        # Ordered by Distrikt Väst, performed but not closed. Utförd needs an
        # assigned resource, and the assignment itself moves the request to
        # Resurs tilldelad, hence two writes (re-browsed: the recordset from
        # create() carries creating_records in its context).
        self.done = self._request(self.district_user, self.vast_team, "61140", "61141")
        done = Request.browse(self.done.id).with_user(self.district_user)
        done.write({"user_id": self.district_user.id})
        done.write({"stage_id": self.env.ref("maintenance.stage_5").id})

        self.all_requests = (
            self.own_here | self.own_elsewhere | self.other_here | self.blank | self.done
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _request(self, user, team=None, cost_center_code=None, kvv_area_code=None):
        vals = {}
        if team is not None:
            vals["maintenance_team_id"] = team.id
        if cost_center_code:
            # Given on create, so the OneCore lookup is skipped.
            vals["cost_center_code"] = cost_center_code
        if kvv_area_code:
            vals["kvv_area_code"] = kvv_area_code
        return create_maintenance_request(self.env(user=user), **vals)

    def _search(self, user, domain):
        """Search as ``user``, limited to this test's requests."""
        return (
            self.env["maintenance.request"]
            .with_user(user)
            .search(domain + [("id", "in", self.all_requests.ids)])
        )

    def assertMatches(self, user, domain, expected):
        self.assertEqual(self._search(user, domain), expected)


@tagged("onecore")
class TestMyFilters(MyFiltersFixture, TransactionCase):
    # ------------------------------------------------------------------
    # ordered_by_my_department
    # ------------------------------------------------------------------
    def test_ordered_by_my_department_as_district_user(self):
        self.assertMatches(
            self.district_user,
            [("ordered_by_my_department", "=", True)],
            self.own_here | self.own_elsewhere | self.done,
        )
        self.assertMatches(
            self.district_user,
            [("ordered_by_my_department", "=", False)],
            self.other_here | self.blank,
        )

    def test_ordered_by_my_department_negation_operators_agree(self):
        """Favorites negate with '= False'; '!= True' must mean the same."""
        self.assertEqual(
            self._search(self.district_user, [("ordered_by_my_department", "!=", True)]),
            self._search(self.district_user, [("ordered_by_my_department", "=", False)]),
        )
        self.assertEqual(
            self._search(self.district_user, [("ordered_by_my_department", "!=", False)]),
            self._search(self.district_user, [("ordered_by_my_department", "=", True)]),
        )

    def test_ordered_by_my_department_as_kundcenter_user(self):
        self.assertMatches(
            self.kundcenter_user,
            [("ordered_by_my_department", "=", True)],
            self.other_here,
        )

    def test_ordered_by_my_department_without_department(self):
        """No department: 'mine' is nothing, 'not mine' is everything —
        never 'everything with an empty department'."""
        self.assertMatches(
            self.blank_user,
            [("ordered_by_my_department", "=", True)],
            self.env["maintenance.request"],
        )
        self.assertMatches(
            self.blank_user,
            [("ordered_by_my_department", "=", False)],
            self.all_requests,
        )

    def test_ordered_by_my_department_matches_the_stamped_form(self):
        """The stamp on the request is stripped; so is the comparison."""
        self.district_user.ad_office_location = "  Distrikt Väst  "

        self.assertMatches(
            self.district_user,
            [("ordered_by_my_department", "=", True)],
            self.own_here | self.own_elsewhere | self.done,
        )

    # ------------------------------------------------------------------
    # in_my_district
    # ------------------------------------------------------------------
    def test_in_my_district_as_district_user(self):
        self.assertMatches(
            self.district_user,
            [("in_my_district", "=", True)],
            self.own_here | self.other_here | self.done,
        )
        self.assertMatches(
            self.district_user,
            [("in_my_district", "=", False)],
            self.own_elsewhere | self.blank,
        )

    def test_in_my_district_sees_archived_teams(self):
        """District teams are archived in prod until kvartersvärdarna start;
        the membership still says which district the user belongs to."""
        self.vast_team.active = False

        self.assertMatches(
            self.district_user,
            [("in_my_district", "=", True)],
            self.own_here | self.other_here | self.done,
        )

    def test_in_my_district_without_team_matches_nothing(self):
        self.assertMatches(
            self.kundcenter_user,
            [("in_my_district", "=", True)],
            self.env["maintenance.request"],
        )
        self.assertMatches(
            self.kundcenter_user,
            [("in_my_district", "=", False)],
            self.all_requests,
        )

    def test_in_my_district_ignores_teams_without_cost_center(self):
        """A membership in e.g. Vitvaror says nothing about a district."""
        vitvaror = create_maintenance_team(self.env, name="Vitvaror (test)")
        vitvaror.member_ids = [(4, self.blank_user.id)]

        self.assertMatches(
            self.blank_user,
            [("in_my_district", "=", True)],
            self.env["maintenance.request"],
        )

    # ------------------------------------------------------------------
    # at_my_teams
    # ------------------------------------------------------------------
    def test_at_my_teams_as_district_user(self):
        self.assertMatches(
            self.district_user,
            [("at_my_teams", "=", True)],
            self.own_here | self.other_here | self.done,
        )
        # Negated it must include requests with no team at all: "hos andra"
        # is everything that is not with me.
        self.assertMatches(
            self.district_user,
            [("at_my_teams", "=", False)],
            self.own_elsewhere | self.blank,
        )

    def test_at_my_teams_without_team_matches_nothing(self):
        self.assertMatches(
            self.kundcenter_user,
            [("at_my_teams", "=", True)],
            self.env["maintenance.request"],
        )

    def test_at_my_teams_as_external_contractor(self):
        """A contractor's env cannot read other users or teams; the field
        must still resolve (sudo inside) and record rules still apply."""
        contractor = create_external_contractor_user(self.env)
        self.vast_team.member_ids = [(4, contractor.id)]

        self.assertMatches(
            contractor,
            [("at_my_teams", "=", True)],
            self.own_here | self.other_here | self.done,
        )

    # ------------------------------------------------------------------
    # in_my_kvv_areas
    # ------------------------------------------------------------------
    def test_in_my_kvv_areas_as_steward(self):
        self.assertMatches(
            self.district_user,
            [("in_my_kvv_areas", "=", True)],
            self.own_here | self.other_here | self.done,
        )
        self.assertMatches(
            self.district_user,
            [("in_my_kvv_areas", "=", False)],
            self.own_elsewhere | self.blank,
        )

    def test_in_my_kvv_areas_without_keycloak_id_matches_nothing(self):
        """A password user has no oauth_uid, so no area can point at them."""
        self.assertFalse(self.blank_user.oauth_uid)

        self.assertMatches(
            self.blank_user,
            [("in_my_kvv_areas", "=", True)],
            self.env["maintenance.request"],
        )

    def test_in_my_kvv_areas_follows_the_kvv_area_master(self):
        """Steward changes land in the master by cron; no request is touched."""
        self.ost_area.responsible_keycloak_id = "keycloak-sub-vast"

        self.assertMatches(
            self.district_user,
            [("in_my_kvv_areas", "=", True)],
            self.own_here | self.own_elsewhere | self.other_here | self.done,
        )

    # ------------------------------------------------------------------
    # is_performed
    # ------------------------------------------------------------------
    def test_is_performed(self):
        self.assertMatches(
            self.district_user, [("is_performed", "=", True)], self.done
        )
        self.assertMatches(
            self.district_user,
            [("is_performed", "=", False)],
            self.own_here | self.own_elsewhere | self.other_here | self.blank,
        )

    # ------------------------------------------------------------------
    # ordered_by_team_id
    # ------------------------------------------------------------------
    def test_ordered_by_team_id_resolves_to_the_members_departments(self):
        """What the team's people ordered — wherever the requests sit now."""
        self.assertMatches(
            self.kundcenter_user,
            [("ordered_by_team_id", "=", self.vast_team.id)],
            self.own_here | self.own_elsewhere | self.done,
        )
        self.assertMatches(
            self.kundcenter_user,
            [("ordered_by_team_id", "!=", self.vast_team.id)],
            self.other_here | self.blank,
        )

    def test_ordered_by_team_id_unions_the_departments_of_all_members(self):
        self.vast_team.member_ids = [(4, self.kundcenter_user.id)]

        self.assertMatches(
            self.blank_user,
            [("ordered_by_team_id", "=", self.vast_team.id)],
            self.own_here | self.own_elsewhere | self.other_here | self.done,
        )

    def test_ordered_by_team_id_without_members_matches_nothing(self):
        empty_team = create_maintenance_team(self.env, cost_center_code="61999")

        self.assertMatches(
            self.district_user,
            [("ordered_by_team_id", "=", empty_team.id)],
            self.env["maintenance.request"],
        )

    def test_ordered_by_team_id_ignores_members_without_department(self):
        """The blank member adds no department, and must not turn the filter
        into 'requests with an empty department'."""
        self.ost_team.member_ids = [(4, self.blank_user.id)]

        self.assertMatches(
            self.district_user,
            [("ordered_by_team_id", "=", self.ost_team.id)],
            self.env["maintenance.request"],
        )

    def test_ordered_by_team_id_accepts_several_teams(self):
        self.ost_team.member_ids = [(4, self.kundcenter_user.id)]

        self.assertMatches(
            self.blank_user,
            [("ordered_by_team_id", "in", [self.vast_team.id, self.ost_team.id])],
            self.own_here | self.own_elsewhere | self.other_here | self.done,
        )

    # ------------------------------------------------------------------
    # Combined, as the favorites will use them
    # ------------------------------------------------------------------
    def test_ordered_by_my_district_at_other_teams(self):
        """What my district ordered that sits with someone else."""
        self.assertMatches(
            self.district_user,
            [("ordered_by_my_department", "=", True), ("at_my_teams", "=", False)],
            self.own_elsewhere,
        )

    def test_in_my_district_ordered_by_others(self):
        """What sits in my district but was ordered elsewhere."""
        self.assertMatches(
            self.district_user,
            [("in_my_district", "=", True), ("ordered_by_my_department", "=", False)],
            self.other_here,
        )


FAVORITES = (
    "filter_ordered_by_my_department_at_others",
    "filter_in_my_district_ordered_by_others",
    "filter_my_kvv_areas",
)
# "Avdelning", not "distrikt", on the first one: the favorite is shared with
# Kundcenter and the other departments that are not a district.
FAVORITE_NAMES = {
    "filter_ordered_by_my_department_at_others": "Beställt av min avdelning hos andra",
    "filter_in_my_district_ordered_by_others": "I mitt distrikt, beställt av andra",
    "filter_my_kvv_areas": "Mina kvartersvärdsområden",
}


@tagged("onecore")
class TestShippedFavorites(MyFiltersFixture, TransactionCase):
    """The three ir.filters records in data/ir_filters.xml and the
    "Mitt distrikt" action + menu in views/my_district_views.xml."""

    def _favorite(self, xml_id):
        return self.env.ref(f"onecore_maintenance_extension.{xml_id}")

    def _profiles(self):
        return {
            "district": self.district_user,
            "kundcenter": self.kundcenter_user,
            "blank": self.blank_user,
        }

    def _run(self, favorite, user):
        """Evaluate a favorite the way the web client does — its domain,
        its group-by and its sort — as ``user``, limited to this test's
        requests. Returns the matching records."""
        Request = self.env["maintenance.request"].with_user(user)
        domain = safe_eval(favorite.domain) + [("id", "in", self.all_requests.ids)]
        group_by = safe_eval(favorite.context).get("group_by", [])
        order = ", ".join(json.loads(favorite.sort)) or None
        Request._read_group(domain, groupby=group_by, aggregates=["__count"])
        return Request.search(domain, order=order)

    # ------------------------------------------------------------------
    # The records
    # ------------------------------------------------------------------
    def test_favorites_are_shared_and_bound_to_no_action(self):
        for xml_id in FAVORITES:
            with self.subTest(favorite=xml_id):
                favorite = self._favorite(xml_id)
                self.assertEqual(favorite.name, FAVORITE_NAMES[xml_id])
                self.assertTrue(favorite.active)
                self.assertEqual(favorite.model_id, "maintenance.request")
                self.assertFalse(favorite.action_id)
                # Empty = shared with everyone
                self.assertFalse(favorite.user_ids)
                self.assertFalse(favorite.is_default)

    def test_favorites_list_under_every_request_action(self):
        """The favorites dropdown only lists filters bound to the current
        action or to none. The stock list and "Mitt distrikt" must both show
        all three."""
        for action_xml_id in (
            "maintenance.hr_equipment_request_action",
            "onecore_maintenance_extension.action_my_district_requests",
        ):
            with self.subTest(action=action_xml_id):
                action = self.env.ref(action_xml_id)
                listed = (
                    self.env["ir.filters"]
                    .with_user(self.district_user)
                    .get_filters("maintenance.request", action_id=action.id)
                )
                self.assertLessEqual(
                    set(FAVORITE_NAMES.values()), {f["name"] for f in listed}
                )

    def test_favorites_evaluate_for_every_profile(self):
        """Domain, group-by and sort must all be valid for the ORM, for a
        user with everything, one with only a department and one with
        nothing. A favorite that raises is a broken dropdown for everyone."""
        for xml_id in FAVORITES:
            favorite = self._favorite(xml_id)
            for profile, user in self._profiles().items():
                with self.subTest(favorite=xml_id, profile=profile):
                    self._run(favorite, user)

    def test_favorites_hide_archived_requests(self):
        """Clicking a favorite drops the "Aktiva ärenden" facet, so the
        favorites carry archive = False themselves."""
        self.own_elsewhere.sudo().write({"archive": True})

        favorite = self._favorite("filter_ordered_by_my_department_at_others")
        self.assertEqual(
            self._run(favorite, self.district_user), self.env["maintenance.request"]
        )

    # ------------------------------------------------------------------
    # What each one answers
    # ------------------------------------------------------------------
    def test_ordered_by_my_department_at_others(self):
        favorite = self._favorite("filter_ordered_by_my_department_at_others")

        self.assertEqual(self._run(favorite, self.district_user), self.own_elsewhere)
        # Kundcenter has no resource group, so everything it ordered is
        # "hos andra".
        self.assertEqual(self._run(favorite, self.kundcenter_user), self.other_here)
        self.assertEqual(
            self._run(favorite, self.blank_user), self.env["maintenance.request"]
        )

    def test_in_my_district_ordered_by_others(self):
        favorite = self._favorite("filter_in_my_district_ordered_by_others")

        self.assertEqual(self._run(favorite, self.district_user), self.other_here)
        for user in (self.kundcenter_user, self.blank_user):
            self.assertEqual(self._run(favorite, user), self.env["maintenance.request"])

    def test_in_my_district_ordered_by_others_is_open_requests_only(self):
        favorite = self._favorite("filter_in_my_district_ordered_by_others")
        Request = self.env["maintenance.request"]
        closed = Request.browse(self.other_here.id).with_user(self.district_user)
        closed.write({"stage_id": self.env.ref("maintenance.stage_6").id})

        self.assertEqual(self._run(favorite, self.district_user), Request)

    def test_my_kvv_areas(self):
        favorite = self._favorite("filter_my_kvv_areas")

        self.assertEqual(
            self._run(favorite, self.district_user),
            self.own_here | self.other_here | self.done,
        )
        for user in (self.kundcenter_user, self.blank_user):
            self.assertEqual(self._run(favorite, user), self.env["maintenance.request"])

    # ------------------------------------------------------------------
    # "Mitt distrikt" menu
    # ------------------------------------------------------------------
    def test_my_district_menu_opens_the_request_list_on_my_district(self):
        menu = self.env.ref("onecore_maintenance_extension.menu_my_district_requests")
        action = self.env.ref("onecore_maintenance_extension.action_my_district_requests")

        self.assertEqual(menu.action, action)
        self.assertEqual(menu.parent_id, self.env.ref("maintenance.menu_m_request"))
        self.assertEqual(action.res_model, "maintenance.request")
        context = safe_eval(action.context)
        self.assertEqual(context.get("search_default_in_my_district"), 1)
        self.assertEqual(context.get("search_default_active"), 1)
        # Same view wiring as the stock request action: kanban on desktop,
        # the mobile view on phones.
        self.assertEqual(action.mobile_view_mode, "mobile")
        self.assertEqual(
            action.view_ids.sorted("sequence").mapped("view_mode"), ["kanban", "mobile"]
        )


MY_FILTER_NAMES = (
    "ordered_by_my_department",
    "ordered_by_others",
    "in_my_district",
    "in_my_kvv_areas",
    "performed",
)


@tagged("onecore")
class TestMyFiltersSearchView(MyFiltersFixture, TransactionCase):
    """The filters in hr_equipment_request_view_search_extension that the
    favorites and the "Mitt distrikt" menu depend on by name."""

    def _search_arch(self):
        arch = self.env["maintenance.request"].get_view(view_type="search")["arch"]
        return etree.fromstring(arch)

    def _filter_domains(self):
        """name -> domain string of every filter with one of our names."""
        return {
            node.get("name"): node.get("domain")
            for node in self._search_arch().iter("filter")
            if node.get("name") in MY_FILTER_NAMES
        }

    def test_search_view_has_the_per_user_filters(self):
        arch = self._search_arch()

        self.assertEqual(set(self._filter_domains()), set(MY_FILTER_NAMES))
        self.assertTrue(arch.xpath("//filter[@name='estate']"))

    def test_per_user_filters_evaluate_for_every_profile(self):
        domains = self._filter_domains()
        for profile, user in (
            ("district", self.district_user),
            ("kundcenter", self.kundcenter_user),
            ("blank", self.blank_user),
        ):
            for name, domain in domains.items():
                with self.subTest(filter=name, profile=profile):
                    self._search(user, safe_eval(domain, {"uid": user.id}))

    def test_per_user_filters_answer_as_the_fields_do(self):
        domains = {name: safe_eval(d) for name, d in self._filter_domains().items()}

        self.assertMatches(
            self.district_user,
            domains["ordered_by_my_department"],
            self.own_here | self.own_elsewhere | self.done,
        )
        self.assertMatches(
            self.district_user, domains["ordered_by_others"], self.other_here | self.blank
        )
        self.assertMatches(
            self.district_user,
            domains["in_my_district"],
            self.own_here | self.other_here | self.done,
        )
        self.assertMatches(
            self.district_user,
            domains["in_my_kvv_areas"],
            self.own_here | self.other_here | self.done,
        )
        self.assertMatches(self.district_user, domains["performed"], self.done)

    def test_my_district_menu_defaults_to_an_existing_filter(self):
        """search_default_<name> is silently ignored when no filter has that
        name; the menu would then open the whole list."""
        action = self.env.ref("onecore_maintenance_extension.action_my_district_requests")
        defaults = [
            key[len("search_default_"):]
            for key in safe_eval(action.context)
            if key.startswith("search_default_")
        ]
        names = {node.get("name") for node in self._search_arch().iter("filter")}

        self.assertEqual(set(defaults), {"in_my_district", "active"})
        self.assertTrue(set(defaults) <= names, names)

    def test_group_by_estate_works_for_a_plain_user(self):
        """estate is related and not stored; grouping must still work for a
        user who is not superuser (Odoo joins related fields with
        compute_sudo, the default for related)."""
        groups = (
            self.env["maintenance.request"]
            .with_user(self.district_user)
            ._read_group(
                [("id", "in", self.all_requests.ids)],
                groupby=["kvv_area_code", "estate"],
                aggregates=["__count"],
            )
        )

        self.assertEqual(sum(count for *_keys, count in groups), len(self.all_requests))
