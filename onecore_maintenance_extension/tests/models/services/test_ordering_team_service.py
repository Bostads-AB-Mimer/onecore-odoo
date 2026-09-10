"""Tests for MIM-1970 — "Beställande resursgrupp" on maintenance requests.

Covers the create() stamp (including the Mina sidor case, where create_uid is
a technical integration user and a derivation would be meaningless), the
backfill cron and its guess stamp, and the search facet that makes the
follow-up views MIM-1975/1976/1977 pure configuration.
"""
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.onecore_maintenance_extension.models.maintenance_ad_unit import (
    normalize_ad_unit,
)

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

    def test_create_from_mimer_nu_ignores_the_category_override(self):
        """The mimer-nu branch returns before the category
        override on purpose. The override picks between the *orderer's own*
        queues, and the orderer here is a tenant — their key request landed in
        Kundcenter's inbox, it was not ordered by the Nyckelbeställningar queue.
        Even an integration user who happens to be a member of that queue must
        not change the answer."""
        integration_user = create_internal_user(self.env)
        self.nyckel.write({"member_ids": [(4, integration_user.id)]})

        request = create_maintenance_request(
            self.env(user=integration_user),
            creation_origin="mimer-nu",
            maintenance_request_category_id=self.key_category.id,
        )

        self.assertEqual(request.ordering_team_id, self.kundcenter)
        self.assertNotEqual(request.ordering_team_id, self.nyckel)

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
    # AD unit (MIM-2011): category → AD → membership
    # ------------------------------------------------------------------
    def _map_ad_unit(self, name, team):
        return self.env["maintenance.ad.unit"].create(
            {"name": name, "team_id": team.id}
        )

    def test_normalize_ad_unit_merges_the_known_prod_variants(self):
        """The three pairs seen among the 33 prod values. Only the HR pair is
        merged by normalisation; Kundcenter/Kundcenterenheten and the
        Besiktings-/Besiktnings- typo are genuinely different strings and get
        one mapping row each (test_two_spellings_can_map_to_the_same_team)."""
        self.assertEqual(
            normalize_ad_unit("HR- och social hållbarhets avdelningen"),
            normalize_ad_unit("HR- och social hållbarhetsavdelningen"),
        )
        self.assertEqual(normalize_ad_unit("  Kundcenter  "), "kundcenter")
        self.assertEqual(normalize_ad_unit("Distrikt   Öst"), "distrikt öst")
        self.assertNotEqual(
            normalize_ad_unit("Kundcenter"), normalize_ad_unit("Kundcenterenheten")
        )
        self.assertNotEqual(
            normalize_ad_unit("Besiktings- och målerienheten"),
            normalize_ad_unit("Besiktnings- och målerienheten"),
        )
        self.assertEqual(normalize_ad_unit(None), "")
        self.assertEqual(normalize_ad_unit(""), "")

    def test_create_teamless_creator_with_mapped_ad_unit_gets_the_team(self):
        """AC 3 — the 990-request gap: a creator in no resource group, but
        with a mapped AD unit, is no longer left empty."""
        self._map_ad_unit("Fastighetsserviceenheten", self.other_team)
        self.teamless_user.write({"ad_office_location": "Fastighetsserviceenheten"})

        request = create_maintenance_request(self.env(user=self.teamless_user))

        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")
        self.assertFalse(request.ordering_backfilled_at)

    def test_create_ad_unit_wins_over_the_lowest_id_membership(self):
        """AC 4 — Annelie/David: a member of a functional group *and* the
        "Internt underhåll" test group always landed on the lowest id. The AD
        unit names the real group."""
        self.other_team.write({"member_ids": [(4, self.district_user.id)]})
        # Baseline: lowest id wins without an AD unit
        self.assertEqual(
            create_maintenance_request(self.env(user=self.district_user)).ordering_team_id,
            self.district_team,
        )

        self._map_ad_unit("Annan enhet", self.other_team)
        self.district_user.write({"ad_office_location": "Annan enhet"})

        request = create_maintenance_request(self.env(user=self.district_user))

        self.assertEqual(request.ordering_team_id, self.other_team)

    def test_create_ad_unit_does_not_require_membership(self):
        """Unlike the category override, the AD rule is not gated on the
        orderer being a member of the mapped team: the whole point is to
        resolve people whose Odoo membership is missing or misleading."""
        self._map_ad_unit("Annan enhet", self.other_team)
        self.district_user.write({"ad_office_location": "Annan enhet"})
        self.assertNotIn(self.district_user, self.other_team.member_ids)

        request = create_maintenance_request(self.env(user=self.district_user))

        self.assertEqual(request.ordering_team_id, self.other_team)

    def test_create_category_override_wins_over_the_ad_unit(self):
        """Kundcenter's two queues are both "Kundcenterenheten" in AD. AD
        before the category would collapse them back into one — the
        category rule has to come first."""
        self._map_ad_unit("Kundcenterenheten", self.inkomna)
        self.kundcenter_user.write({"ad_office_location": "Kundcenterenheten"})

        key_request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.key_category.id,
        )
        plain_request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.plain_category.id,
        )

        self.assertEqual(key_request.ordering_team_id, self.nyckel)
        self.assertEqual(plain_request.ordering_team_id, self.inkomna)

    def test_create_ad_unit_uses_owner_over_creator(self):
        """Same orderer precedence as every other rule: owner_user_id first."""
        self._map_ad_unit("Annan enhet", self.other_team)
        self.teamless_user.write({"ad_office_location": "Annan enhet"})

        request = create_maintenance_request(
            self.env(user=self.district_user), owner_user_id=self.teamless_user.id
        )

        self.assertEqual(request.ordering_team_id, self.other_team)

    def test_create_from_mimer_nu_ignores_the_ad_unit(self):
        """Tenant reports go to Kundcenter regardless of what the integration
        user's own AD unit says — same reasoning as for the category override."""
        integration_user = create_internal_user(self.env)
        self._map_ad_unit("IT-enheten", self.other_team)
        integration_user.write({"ad_office_location": "IT-enheten"})

        request = create_maintenance_request(
            self.env(user=integration_user), creation_origin="mimer-nu"
        )

        self.assertEqual(request.ordering_team_id, self.kundcenter)

    def test_create_ad_lookup_is_normalised(self):
        """The mapping row is stored as AD spells it; the user's value may
        differ in case, padding or the stray space before "avdelningen"."""
        self._map_ad_unit("HR- och social hållbarhetsavdelningen", self.other_team)
        self.teamless_user.write(
            {"ad_office_location": "  hr- och social hållbarhets   avdelningen "}
        )

        request = create_maintenance_request(self.env(user=self.teamless_user))

        self.assertEqual(request.ordering_team_id, self.other_team)

    def test_two_spellings_can_map_to_the_same_team(self):
        """Why this is a table and not a Char on the team."""
        self._map_ad_unit("Besiktings- och målerienheten", self.other_team)
        self._map_ad_unit("Besiktnings- och målerienheten", self.other_team)
        typo_user = create_internal_user(
            self.env, ad_office_location="Besiktings- och målerienheten"
        )
        correct_user = create_internal_user(
            self.env, ad_office_location="Besiktnings- och målerienheten"
        )

        self.assertEqual(
            create_maintenance_request(self.env(user=typo_user)).ordering_team_id,
            self.other_team,
        )
        self.assertEqual(
            create_maintenance_request(self.env(user=correct_user)).ordering_team_id,
            self.other_team,
        )

    def test_duplicate_normalised_spelling_is_rejected(self):
        """Two rows for the same unit would let whichever search() returns
        first win silently. The constraint is on the normalised value."""
        self._map_ad_unit("Kundcenter", self.inkomna)

        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._map_ad_unit("  KUNDCENTER ", self.nyckel)

    def test_editing_a_row_into_a_duplicate_is_rejected(self):
        self._map_ad_unit("Kundcenter", self.inkomna)
        row = self._map_ad_unit("Kundcenterenheten", self.inkomna)

        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            row.write({"name": "kundcenter"})
            self.env.flush_all()

    def test_create_unmapped_ad_unit_changes_nothing(self):
        """AC 6 — a value nobody has mapped (Projektenheten will never work in
        Odoo) falls through to membership exactly as before MIM-2011."""
        self.district_user.write({"ad_office_location": "Projektenheten"})
        self.teamless_user.write({"ad_office_location": "Projektenheten"})

        self.assertEqual(
            create_maintenance_request(self.env(user=self.district_user)).ordering_team_id,
            self.district_team,
        )
        request = create_maintenance_request(self.env(user=self.teamless_user))
        self.assertFalse(request.ordering_team_id)
        self.assertTrue(request.ordering_backfilled_at)

    def test_create_mapping_to_an_archived_team_is_ignored(self):
        """AC 7 — Besiktning och Måleri, Fastighetsutveckling and IT were
        created archived (2026-09-07) so the mapping can be entered ahead of
        time. The row must stay inert until the team is unarchived."""
        archived_team = create_maintenance_team(self.env, name="Arkiverad enhet")
        self._map_ad_unit("IT-enheten", archived_team)
        archived_team.action_archive()
        self.district_user.write({"ad_office_location": "IT-enheten"})
        self.teamless_user.write({"ad_office_location": "IT-enheten"})

        self.assertEqual(
            create_maintenance_request(self.env(user=self.district_user)).ordering_team_id,
            self.district_team,
        )
        self.assertFalse(
            create_maintenance_request(self.env(user=self.teamless_user)).ordering_team_id
        )

    def test_backfill_applies_the_ad_unit_rule(self):
        """AC 5 — same rule for old requests, from a precomputed map."""
        self._map_ad_unit("Fastighetsserviceenheten", self.other_team)
        self.teamless_user.write({"ad_office_location": "Fastighetsserviceenheten"})
        request = create_maintenance_request(self.env(user=self.teamless_user))
        self._clear_ordering(request)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.other_team)
        self.assertEqual(request.ordering_cost_center_code, "61130")
        self.assertTrue(request.ordering_backfilled_at)

    def test_backfill_category_override_wins_over_the_ad_unit(self):
        self._map_ad_unit("Kundcenterenheten", self.inkomna)
        self.kundcenter_user.write({"ad_office_location": "Kundcenterenheten"})
        request = create_maintenance_request(
            self.env(user=self.kundcenter_user),
            maintenance_request_category_id=self.key_category.id,
        )
        self._clear_ordering(request)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.nyckel)

    def test_backfill_ad_unit_wins_over_the_lowest_id_membership(self):
        self.other_team.write({"member_ids": [(4, self.district_user.id)]})
        self._map_ad_unit("Annan enhet", self.other_team)
        self.district_user.write({"ad_office_location": "Annan enhet"})
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.other_team)

    def test_backfill_never_uses_a_mapping_to_an_archived_team(self):
        """The precomputed map must re-check the team's active state itself,
        same as test_backfill_never_uses_an_archived_preferred_team."""
        archived_team = create_maintenance_team(self.env, name="Arkiverad enhet")
        self._map_ad_unit("IT-enheten", archived_team)
        self.district_user.write({"ad_office_location": "IT-enheten"})
        request = create_maintenance_request(self.env(user=self.district_user))
        self._clear_ordering(request)
        archived_team.action_archive()

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.district_team)

    def test_backfill_counts_the_ad_unit_of_an_archived_creator(self):
        """Old requests were often created by people who have since left. An
        archived user's AD unit is still the truthful answer for what they
        ordered back then — the user map must not be active-filtered."""
        self._map_ad_unit("Fastighetsserviceenheten", self.other_team)
        self.teamless_user.write({"ad_office_location": "Fastighetsserviceenheten"})
        request = create_maintenance_request(self.env(user=self.teamless_user))
        self._clear_ordering(request)
        self.teamless_user.action_archive()

        self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertEqual(request.ordering_team_id, self.other_team)

    def test_create_and_backfill_agree_on_every_precedence_case(self):
        """The precedence lives in one place (_first_team), but the two paths
        still feed it different lookups — a search per request on create,
        prebuilt maps in the backfill. This is the test that catches them
        drifting apart: whatever create stamps, the backfill must reproduce
        for the same orderer and category."""
        self._map_ad_unit("Kundcenterenheten", self.inkomna)
        self._map_ad_unit("Fastighetsserviceenheten", self.other_team)
        self.kundcenter_user.write({"ad_office_location": "Kundcenterenheten"})
        self.teamless_user.write({"ad_office_location": "Fastighetsserviceenheten"})
        self.district_user.write({"ad_office_location": "Enhet ingen mappat"})

        cases = [
            # category beats AD
            (self.kundcenter_user, self.key_category),
            # AD beats the lowest-id membership
            (self.kundcenter_user, self.plain_category),
            # AD resolves someone with no team at all
            (self.teamless_user, self.plain_category),
            # unmapped AD value falls through to membership
            (self.district_user, self.plain_category),
        ]
        for user, category in cases:
            with self.subTest(user=user.login, category=category.name):
                stamped = create_maintenance_request(
                    self.env(user=user),
                    maintenance_request_category_id=category.id,
                )
                guessed = create_maintenance_request(
                    self.env(user=user),
                    maintenance_request_category_id=category.id,
                )
                self._clear_ordering(guessed)

                self.env["maintenance.request"]._cron_backfill_ordering_team()

                self.assertEqual(guessed.ordering_team_id, stamped.ordering_team_id)

    def test_ad_unit_mapping_is_read_only_for_plain_users(self):
        """The business edits the table; everybody else only reads it."""
        plain_user = create_internal_user(
            self.env, group_ids=[(6, 0, [self.env.ref("base.group_user").id])]
        )
        self._map_ad_unit("Kundcenter", self.inkomna)

        self.assertTrue(self.env(user=plain_user)["maintenance.ad.unit"].search([]))
        with self.assertRaises(AccessError):
            self.env(user=plain_user)["maintenance.ad.unit"].create(
                {"name": "IT-enheten", "team_id": self.other_team.id}
            )

    def test_ad_unit_form_can_pick_an_archived_team(self):
        """The mapping has to be enterable *before* the group starts working
        in Odoo, and those groups are deliberately created archived. A plain
        many2one hides archived records from its dropdown, so without
        active_test=False on the field they cannot be picked at all — while
        the field's help text and _ad_team's archived-team handling both
        promise that they can. test_create_mapping_to_an_archived_team_is_ignored
        covers the resolution side, but it builds the row through create()
        and so never touches the dropdown."""
        archived_team = create_maintenance_team(self.env, name="Arkiverad enhet")
        archived_team.action_archive()

        view = self.env.ref(
            "onecore_maintenance_extension.maintenance_ad_unit_view_list"
        )
        self.assertIn("active_test", view.arch_db)

        Team = self.env["maintenance.team"]
        # What the dropdown does by default: the team is not offered at all
        self.assertNotIn(
            archived_team.id,
            [row[0] for row in Team.name_search("Arkiverad enhet")],
        )
        # What the view's context makes it do instead
        self.assertIn(
            archived_team.id,
            [
                row[0]
                for row in Team.with_context(active_test=False).name_search(
                    "Arkiverad enhet"
                )
            ],
        )

    def test_ad_unit_menu_sits_under_configuration(self):
        menu = self.env.ref("onecore_maintenance_extension.menu_maintenance_ad_unit")

        self.assertEqual(
            menu.parent_id, self.env.ref("maintenance.menu_maintenance_configuration")
        )
        self.assertEqual(menu.action.res_model, "maintenance.ad.unit")

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

    def test_archived_kundcenter_is_never_the_orderer(self):
        """kundcenter_team() used to be a plain env.ref, which
        ignores ``active`` — the one team lookup that could stamp an archived
        team. Now it goes through search() like every other lookup, on both
        the create path and the backfill."""
        self.kundcenter.action_archive()

        request = create_maintenance_request(
            self.env(user=self.teamless_user), creation_origin="mimer-nu"
        )
        self.assertFalse(request.ordering_team_id)
        # Resolved to nothing at create — stamped so the backfill will not
        # revisit it (test_create_time_unresolved_orderer_is_not_rederived_later)
        self.assertTrue(request.ordering_backfilled_at)

        self._clear_ordering(request)
        first = self.env["maintenance.request"]._cron_backfill_ordering_team()
        second = self.env["maintenance.request"]._cron_backfill_ordering_team()

        self.assertGreaterEqual(first, 1)
        self.assertFalse(request.ordering_team_id)
        self.assertTrue(request.ordering_backfilled_at)
        self.assertEqual(second, 0)

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
