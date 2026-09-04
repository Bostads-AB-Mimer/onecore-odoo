"""Tests for MIM-1970 — "Beställande resursgrupp" on maintenance requests.

Covers the create() stamp (including the Mina sidor case, where create_uid is
a technical integration user and a derivation would be meaningless), the
backfill cron and its guess stamp, and the search facet that makes the
follow-up views MIM-1975/1976/1977 pure configuration.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import (
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
)


@tagged("onecore")
class TestOrderingTeamService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.kundcenter = self.env.ref("onecore_maintenance_extension.7")

        self.district_user = create_internal_user(self.env)
        self.district_team = create_maintenance_team(
            self.env,
            name="Distrikt Testväst",
            cost_center_code="61140",
            member_ids=[(4, self.district_user.id)],
        )

        self.other_user = create_internal_user(self.env)
        self.other_team = create_maintenance_team(
            self.env,
            name="Annan resursgrupp",
            cost_center_code="61130",
            member_ids=[(4, self.other_user.id)],
        )

        # No team at all — falls through to Kundcenter
        self.teamless_user = create_internal_user(self.env)

        # Kundcenter's two queues (MIM-1970: same person in both is exactly
        # the case the category override exists for).
        self.inkomna = self.kundcenter
        self.nyckel = create_maintenance_team(self.env, name="Nyckelbeställningar")
        self.kundcenter_user = create_internal_user(self.env)
        self.inkomna.write({"member_ids": [(4, self.kundcenter_user.id)]})
        self.nyckel.write({"member_ids": [(4, self.kundcenter_user.id)]})

        self.key_category = self.env["maintenance.request.category"].create(
            {"name": "Beställning av extra nyckel", "preferred_ordering_team_id": self.nyckel.id}
        )
        self.plain_category = self.env.ref("onecore_maintenance_extension.category_1")

    def _clear_ordering(self, *requests):
        """Make a request look like it predates MIM-1970."""
        for request in requests:
            request.sudo().write(
                {
                    "ordering_team_id": False,
                    "ordering_cost_center_code": False,
                    "ordering_backfilled_at": False,
                }
            )

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def test_create_stamps_the_creators_team(self):
        request = create_maintenance_request(self.env(user=self.district_user))

        self.assertEqual(request.ordering_team_id, self.district_team)
        # Denormalised so the district facet does not have to join
        self.assertEqual(request.ordering_cost_center_code, "61140")
        # Not a guess: it was recorded while we knew
        self.assertFalse(request.ordering_backfilled_at)

    def test_create_prefers_owner_over_creator(self):
        """owner_user_id is the orderer when it is set; create_uid is a fallback."""
        request = create_maintenance_request(
            self.env(user=self.district_user), owner_user_id=self.other_user.id
        )

        self.assertEqual(request.create_uid, self.district_user)
        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")

    def test_create_leaves_the_orderer_empty_without_a_team(self):
        """No Kundcenter fallback for a group-less creator.

        Kundcenter distributes every request in the organisation, so their
        bucket is the biggest one by construction. Filing "we could not tell"
        in it would mix ~990 prod requests from 29 group-less creators in with
        the ones Kundcenter genuinely registered, unseparably. Empty is the
        truthful answer.
        """
        request = create_maintenance_request(self.env(user=self.teamless_user))

        self.assertFalse(request.ordering_team_id)
        self.assertFalse(request.ordering_cost_center_code)
        # The timestamp IS stamped even though nothing was resolved — see
        # test_create_time_unresolved_orderer_is_not_rederived_later for why.
        self.assertTrue(request.ordering_backfilled_at)

    def test_create_time_unresolved_orderer_is_not_rederived_later(self):
        """What the timestamp above exists to prevent: without it, a request
        genuinely resolved to "no team" at create time would be
        indistinguishable from a true pre-MIM-1970 legacy row. The backfill
        would then "fix" it later using the creator's current membership —
        rewriting a history that was already correctly empty."""
        request = create_maintenance_request(self.env(user=self.teamless_user))
        self.assertFalse(request.ordering_team_id)

        # The creator joins a team after the request already exists.
        self.district_team.write({"member_ids": [(4, self.teamless_user.id)]})

        processed = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(processed, 0)
        self.assertFalse(request.ordering_team_id)

    def test_create_still_routes_mimer_nu_to_kundcenter(self):
        """The one deliberate Kundcenter claim survives the fallback removal:
        they distribute the whole organisation's inflow, so the tenant reports
        genuinely are theirs."""
        request = create_maintenance_request(
            self.env(user=self.teamless_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.ordering_team_id, self.kundcenter)

    def test_create_from_mimer_nu_resolves_kundcenter_not_the_integration_user(self):
        """MIM-1970's decisive case.

        Mina sidor-ärenden arrive over XML-RPC with a technical integration
        user as create_uid. Here that user is deliberately a member of another
        team: the stamp must still be Kundcenter, because the tenant ordered
        the request and the integration user's membership says nothing. This
        is exactly what a derived field would get wrong — and it would get it
        wrong for the largest inflow.
        """
        integration_user = create_internal_user(self.env)
        self.other_team.write({"member_ids": [(4, integration_user.id)]})

        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.create_uid, integration_user)
        self.assertEqual(request.ordering_team_id, self.kundcenter)
        self.assertNotEqual(request.ordering_team_id, self.other_team)

    def test_create_keeps_a_team_stamped_by_the_caller(self):
        """core over XML-RPC (and later MIM-1971) wins over the derivation."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            ordering_team_id=self.other_team.id,
            ordering_cost_center_code="61130",
        )

        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")

    def test_create_fills_the_district_code_when_only_the_team_was_stamped(self):
        """A caller may pass just the team. The denormalised code has to
        follow, or the district facet misses the request forever — the
        backfill only ever revisits rows without an ordering team."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            ordering_team_id=self.other_team.id,
        )

        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")

    def test_create_member_of_two_teams_gets_the_lower_id_by_default(self):
        """Baseline the category override is meant to change: without a
        matching category, someone in both Kundcenter queues always lands on
        the older one (lowest id), same as any other multi-membership."""
        request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.plain_category.id,
        )

        self.assertEqual(request.ordering_team_id, self.inkomna)

    def test_create_category_override_wins_for_a_member_of_the_preferred_team(self):
        """MIM-1970's Kundcenter fix: the category names which of the
        orderer's own teams should win, instead of the lowest-id default."""
        request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.key_category.id,
        )

        self.assertEqual(request.ordering_team_id, self.nyckel)

    def test_create_category_override_uses_owner_over_creator(self):
        """The override must respect the same owner-over-creator precedence
        as the plain path (test_create_prefers_owner_over_creator) — it reads
        the same ``orderer``, not create_uid directly."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            owner_user_id=self.kundcenter_user.id,
            maintenance_request_category_id=self.key_category.id,
        )

        self.assertEqual(request.create_uid, self.district_user)
        self.assertEqual(request.ordering_team_id, self.nyckel)

    def test_create_category_override_ignored_for_a_non_member(self):
        """Josefin Sjöberg: kvartersvärdar use the same key-order category.
        The override must never fire off the category alone, or a
        kvartersvärd's cylinderbyte would get credited to Kundcenter."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            maintenance_request_category_id=self.key_category.id,
        )

        self.assertEqual(request.ordering_team_id, self.district_team)
        self.assertNotEqual(request.ordering_team_id, self.nyckel)

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------
    def test_backfill_stamps_old_requests_and_marks_them_as_guessed(self):
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        processed = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertGreaterEqual(processed, 1)
        self.assertEqual(request.ordering_team_id, self.district_team)
        self.assertEqual(request.ordering_cost_center_code, "61140")
        # The stamp is what separates a guess from a recorded fact
        self.assertTrue(request.ordering_backfilled_at)

    def test_backfill_never_touches_team_resource_or_stage(self):
        """Display only: the backfill must not reroute anything."""
        request = create_maintenance_request(
            self.env(user=self.district_user),
            maintenance_team_id=self.other_team.id,
            user_id=self.other_user.id,
        )
        self._clear_ordering(request)
        team_before = request.maintenance_team_id
        user_before = request.user_id
        stage_before = request.stage_id

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.maintenance_team_id, team_before)
        self.assertEqual(request.user_id, user_before)
        self.assertEqual(request.stage_id, stage_before)

    def test_backfill_is_self_consuming(self):
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        first = self.env["maintenance.request"]._cron_backfill_ordering_team()
        second = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)

    def test_backfill_resolves_mimer_nu_to_kundcenter(self):
        integration_user = create_internal_user(self.env)
        self.other_team.write({"member_ids": [(4, integration_user.id)]})
        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )
        self._clear_ordering(request)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.kundcenter)

    def test_backfill_stamps_unresolvable_requests_without_a_team(self):
        """A group-less creator leaves the team empty, but the timestamp is
        still written — otherwise the domain stops being self-consuming and
        those ~990 prod rows come back every hour, forever."""
        request = create_maintenance_request(self.env(user=self.teamless_user))
        self._clear_ordering(request)

        first = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertGreaterEqual(first, 1)
        self.assertFalse(request.ordering_team_id)
        self.assertFalse(request.ordering_cost_center_code)
        # "Looked at it, could not tell" — that is what makes it drop out
        self.assertTrue(request.ordering_backfilled_at)

        second = self.env["maintenance.request"]._cron_backfill_ordering_team()
        self.assertEqual(second, 0)

    def test_backfill_applies_the_category_override_too(self):
        """Old key-order requests get the same fix as new ones — the override
        reads the category stored on the historical request itself."""
        request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.key_category.id,
        )
        self._clear_ordering(request)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.nyckel)

    def test_backfill_never_uses_an_archived_preferred_team(self):
        """Mirrors test_archived_team_is_never_the_orderer for the category
        override. The backfill's precomputed map must re-check the preferred
        team's active state itself — a plain field read from the category
        does not, and would silently stamp an archived team forever (the
        domain is self-consuming)."""
        request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.key_category.id,
        )
        self._clear_ordering(request)
        self.nyckel.action_archive()

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertNotEqual(request.ordering_team_id, self.nyckel)
        self.assertEqual(request.ordering_team_id, self.inkomna)

    def test_backfill_leaves_no_chatter_note(self):
        """SKIP_FIELDS: the backfill writes outside the creating_records
        context, so without it every stamped request would get a note."""
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)
        messages_before = len(request.message_ids)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(len(request.message_ids), messages_before)

    # ------------------------------------------------------------------
    # Cron record / search facet
    # ------------------------------------------------------------------
    def test_backfill_cron_ships_inactive(self):
        """The cron must NOT run on deploy.

        The five district teams are archived in prod until the kvartersvärdar
        start working in Odoo, and search() hides archived records from the
        derivation. Running the backfill before they are unarchived stamps
        their 50 members with a functional group instead of their district —
        permanently, because the domain is self-consuming. Someone flipping
        this to True has to change this test and read why first.
        """
        cron = self.env.ref(
            "onecore_maintenance_extension.ir_cron_backfill_ordering_team"
        )

        self.assertEqual(cron.model_id.model, "maintenance.request")
        self.assertFalse(cron.active)
        self.assertIn("_cron_backfill_ordering_team", cron.code)
        self.assertEqual((cron.interval_number, cron.interval_type), (1, "hours"))

    def test_archived_team_is_never_the_orderer(self):
        """Archived teams are invisible to search(), so they can neither be
        stamped nor silently win the lowest-id tie-break. This is what makes
        the deploy safe while the districts are archived — and what makes the
        attribution change the day they are unarchived."""
        archived_user = create_internal_user(self.env)
        archived_team = create_maintenance_team(
            self.env,
            name="Arkiverat distrikt",
            cost_center_code="61199",
            member_ids=[(4, archived_user.id)],
        )
        archived_team.action_archive()

        request = create_maintenance_request(self.env(user=archived_user))

        self.assertNotEqual(request.ordering_team_id, archived_team)
        self.assertFalse(request.ordering_team_id)
        self.assertFalse(request.ordering_cost_center_code)

    def test_search_view_exposes_the_facet_and_grouping(self):
        """What makes MIM-1975/1976/1977 configuration instead of development."""
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_search_extension"
        )

        self.assertIn('name="ordering_team_id"', view.arch_db)
        self.assertIn('name="ordering_cost_center_code"', view.arch_db)
        self.assertIn("'group_by': 'ordering_team_id'", view.arch_db)

    def test_district_orderer_filters_match_on_code_not_name(self):
        """A favorite built by typing a team name into the search box stores an
        ilike on the (translatable, renameable) name and goes silently empty
        when the team is renamed — and team names have been renamed in prod.
        These click-path filters pair on cost_center_code instead, which is the
        rule MIM-1967 established and what 1975/1976/1977 must build on."""
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_search_extension"
        )
        seeded = {
            "onecore_maintenance_extension.5": "61110",  # Distrikt Mitt
            "onecore_maintenance_extension.4": "61120",  # Distrikt Norr
            "onecore_maintenance_extension.3": "61130",  # Distrikt Öst
            "onecore_maintenance_extension.2": "61140",  # Distrikt Väst
            "onecore_maintenance_extension.6": "61150",  # Studentteam
        }
        for xml_id, code in seeded.items():
            # The filter is worthless if it names a code no team carries
            self.assertEqual(self.env.ref(xml_id).cost_center_code, code)
            self.assertIn(
                "('ordering_cost_center_code', '=', '%s')" % code, view.arch_db
            )
        # No filter may pair on the team name
        self.assertNotIn("ordering_team_id', 'ilike'", view.arch_db)
