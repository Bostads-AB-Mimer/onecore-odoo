"""Beställande resursgrupp on maintenance requests (MIM-1970).

Who *ordered* the request, as opposed to who it currently sits with
(``maintenance_team_id``). Stamped at create and never recomputed on read:

* ``create_uid`` names a person, not a resource group, and a person can be a
  member of several teams — and can move between them.
* A report that derives the orderer at read time rewrites history: "ordered by
  the district in March" must not become a different answer in May because
  somebody changed department.
* Mina sidor-ärenden are created over XML-RPC with a technical integration
  user as ``create_uid``, so a derivation is meaningless for the largest
  inflow. Those are resolved from ``creation_origin`` to Kundcenter instead —
  never from the integration user's team membership.

Write path only: create() and the backfill cron. The read path stays free of
work (MIM-1869).
"""

import logging

from odoo import fields

from ..constants import MIMER_NU_ORIGIN
from ..maintenance_ad_unit import normalize_ad_unit

_logger = logging.getLogger(__name__)

# MIM-1916: resolve teams by xml-id, never by their (translatable) name.
KUNDCENTER_TEAM_XML_ID = "onecore_maintenance_extension.7"


class OrderingTeamService:
    """Resolve, stamp and backfill the ordering team of a request."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve_orderer_team(self, orderer):
        """First team ``orderer`` is a member of, or an empty recordset.

        Shared with MaintenanceStageManager.resolve_return_team so that "the
        orderer's team" has exactly one definition.
        """
        if not orderer:
            return self.env["maintenance.team"]
        return (
            self.env["maintenance.team"]
            .sudo()
            .search([("member_ids", "in", [orderer.id])], limit=1)
        )

    def kundcenter_team(self):
        """The Kundcenter team, or an empty recordset when missing or archived.

        env.ref is a plain browse and ignores ``active``; the search() is what
        keeps an archived Kundcenter from being stamped, same as every other
        team lookup here (test_archived_team_is_never_the_orderer).
        """
        team = self.env.ref(KUNDCENTER_TEAM_XML_ID, raise_if_not_found=False)
        if not team:
            return self.env["maintenance.team"]
        return self.env["maintenance.team"].sudo().search([("id", "=", team.id)], limit=1)

    def resolve_ordering_team(self, request):
        """The resource group that ordered ``request``."""
        if request.creation_origin == MIMER_NU_ORIGIN:
            # A tenant ordered this, not a resource group. create_uid is the
            # technical integration user, so its team membership says nothing:
            # deriving from it would let a single membership change silently
            # claim that some team ordered thousands of tenant reports.
            # The category override is deliberately not consulted either: it
            # picks between the *orderer's own* queues, and the orderer here is
            # a tenant — a tenant's key request was not ordered by Kundcenter's
            # Nyckelbeställningar queue, it landed in their inbox.
            return self.kundcenter_team()
        orderer = request.owner_user_id or request.create_uid
        # No Kundcenter fallback at the end, deliberately. Kundcenter
        # distributes every request in the organisation, so their bucket is the
        # largest one by construction — quietly filing "we could not tell" in
        # it would mix 990 requests from 29 group-less creators (prod,
        # 2026-09-03) in with the ones they genuinely registered, and nobody
        # could separate them afterwards. An empty ordering team is the
        # truthful answer: this request has no known ordering unit. An unmapped
        # or unknown AD value falls all the way through too, exactly as before
        # MIM-2011.
        return self._first_team(
            lambda: self._preferred_category_team(
                request.maintenance_request_category_id, orderer
            ),
            lambda: self._ad_team(orderer),
            lambda: self.resolve_orderer_team(orderer),
        ) or self.env["maintenance.team"]

    @staticmethod
    def _first_team(*candidates):
        """First candidate that resolves to a team, or None.

        THE precedence — category → AD → membership — and the only place it is
        written down. Both write paths call this with their own lookups: the
        create path resolves each candidate with a search(), the backfill
        resolves them from maps it built once for the whole batch. The lookups
        differ on purpose (no per-row query in the backfill); the order must
        not.

        PR #286 review: before this, the order was spelled out twice and kept
        in sync by a comment. A rule added to one path and forgotten in the
        other makes newly created and backfilled requests answer differently
        for the same orderer, silently — which has happened once already, and
        is why test_backfill_never_uses_an_archived_preferred_team exists.
        """
        for candidate in candidates:
            team = candidate()
            if team:
                return team
        return None

    def _category_team_from_map(self, record, orderer, category_overrides):
        """The category override for ``record``, resolved from a prebuilt map.

        The backfill's counterpart to _preferred_category_team: same rule,
        including that it only fires when the orderer is actually a member of
        the preferred team.
        """
        override = category_overrides.get(record.maintenance_request_category_id.id)
        if override and orderer.id in override[1]:
            return override[0]
        return None

    def _ad_team(self, orderer):
        """Team mapped to ``orderer``'s AD unit, or an empty recordset.

        The raw AD value is normalised here, never at storage, so the SSO
        write and the seed import give the same answer. The mapping table is
        matched on the normalised value — never on a team name (MIM-1916).
        """
        if not orderer:
            return self.env["maintenance.team"]
        # sudo: the orderer may be read from a contractor's or the RPC
        # integration user's env, which has no business reading res.users.
        normalized = normalize_ad_unit(orderer.sudo().ad_office_location)
        if not normalized:
            return self.env["maintenance.team"]
        unit = (
            self.env["maintenance.ad.unit"]
            .sudo()
            .search([("name_normalized", "=", normalized)], limit=1)
        )
        if not unit:
            return self.env["maintenance.team"]
        # search(), not a plain field read: a mapping row may point at a team
        # that is archived on purpose (new orderer groups are created archived
        # until the unit starts working in Odoo) — it must not win until then
        # (test_archived_team_is_never_the_orderer).
        return (
            self.env["maintenance.team"]
            .sudo()
            .search([("id", "=", unit.team_id.id)], limit=1)
        )

    def _preferred_category_team(self, category, orderer):
        """Category-specific tie-break for someone in several teams.

        Anna Lundberg (Kundcenter) needs "Nyckelbeställningar" followed up
        apart from "Inkomna serviceanmälningar", but the same people are
        members of both — the ordinary "first team by id" rule always picks
        the older queue. Josefin Sjöberg: the key-order category is also used
        by kvartersvärdar, so this can never key off the category alone — it
        only fires when the orderer is actually a member of that category's
        preferred team, or a kvartersvärd's cylinderbyte would get credited
        to Kundcenter.
        """
        if not orderer or not category or not category.sudo().active:
            return self.env["maintenance.team"]
        team = category.sudo().preferred_ordering_team_id
        if not team:
            return self.env["maintenance.team"]
        # search(), not a plain field read: an archived preferred team must
        # never win, same as any other team (test_archived_team_is_never_the_orderer).
        return (
            self.env["maintenance.team"]
            .sudo()
            .search(
                [("id", "=", team.id), ("member_ids", "in", [orderer.id])], limit=1
            )
        )

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def populate(self, request):
        """Stamp the ordering team on ``request``. Returns True when written.

        A request that already carries an ordering team is left alone, so a
        caller that stamped the field itself (core over XML-RPC, later
        MIM-1971) wins over the derivation — same contract as the district
        snapshot in ManagementAreaService.populate.
        """
        request.ensure_one()
        if request.ordering_team_id:
            # The caller stamped the team itself. Keep it, but make the
            # denormalised district code follow: a caller that passes only the
            # team would otherwise leave it NULL forever — the backfill's
            # "ordering_team_id = False" domain can never come back for it, and
            # the "Beställande distrikt" facet would silently miss the request.
            if not request.ordering_cost_center_code:
                code = request.ordering_team_id.cost_center_code
                if code:
                    request.sudo().write({"ordering_cost_center_code": code})
            return False
        team = self.resolve_ordering_team(request)
        if not team:
            # No team to record, but stamp the timestamp anyway — same as
            # backfill_batch does for its own unresolvable rows. Without it
            # this request is indistinguishable from a true pre-MIM-1970
            # legacy row: the self-consuming backfill domain would revisit it
            # later and derive a team from the creator's *then-current*
            # membership, silently rewriting a history that was already
            # correctly "no team" at create time.
            request.sudo().write({"ordering_backfilled_at": fields.Datetime.now()})
            return False
        # sudo: creators over RPC (mimer.nu) and contractors must not be
        # blocked by record rules when the stamp is written.
        request.sudo().write(self._stamp_vals(team))
        return True

    @staticmethod
    def _stamp_vals(team, backfilled_at=None):
        """Ordering fields for ``team``. Nothing else is ever written."""
        vals = {
            "ordering_team_id": team.id,
            # Denormalised so the district facet does not have to join.
            "ordering_cost_center_code": team.cost_center_code or False,
        }
        if backfilled_at:
            vals["ordering_backfilled_at"] = backfilled_at
        return vals

    # ------------------------------------------------------------------
    # Backfill (cron) — ordering fields only, never team/resource/stage
    # ------------------------------------------------------------------
    def backfill_batch(self, limit=5000):
        """Stamp up to ``limit`` requests created before MIM-1970.

        The guess is derived from who created the request and which team they
        belong to *today* — the best that can be reconstructed after the fact.
        ``ordering_backfilled_at`` marks it as exactly that, so guessed rows
        stay distinguishable from the ones stamped at create.

        Pure DB work, no HTTP, hence the large batch. Requests whose orderer
        cannot be resolved (creator in no resource group) are stamped with the
        timestamp alone and keep an empty team — the truthful answer, and what
        keeps the domain self-consuming: without that stamp those ~990 rows
        would come back every single hour forever. Same pattern as
        ManagementAreaService.backfill_batch stamping unresolvable requests.
        """
        Request = self.env["maintenance.request"].sudo()
        records = Request.search(
            [
                ("ordering_team_id", "=", False),
                ("ordering_backfilled_at", "=", False),
            ],
            order="id desc",
            limit=limit,
        )
        if not records:
            return 0

        kundcenter = self.kundcenter_team()
        user_to_team = self._member_team_map()
        category_overrides = self._category_preferred_team_members()
        ad_teams = self._ad_team_map()
        user_to_ad_unit = self._user_ad_unit_map() if ad_teams else {}
        now = fields.Datetime.now()
        groups = {}  # team id (or False when unresolved) -> request ids
        for record in records:
            if record.creation_origin == MIMER_NU_ORIGIN:
                # Kundcenter distributes every request in the organisation, so
                # they are the right owner of the tenant inflow.
                team = kundcenter
            else:
                orderer = record.owner_user_id or record.create_uid
                team = None
                if orderer:
                    # Same order as the create path, from the one place it is
                    # defined. Only the lookups differ: maps built once for
                    # the batch instead of a search per row.
                    team = self._first_team(
                        lambda: self._category_team_from_map(
                            record, orderer, category_overrides
                        ),
                        lambda: ad_teams.get(user_to_ad_unit.get(orderer.id)),
                        lambda: user_to_team.get(orderer.id),
                    )
            groups.setdefault(team.id if team else False, []).append(record.id)

        Team = self.env["maintenance.team"].sudo()
        resolved = 0
        for team_id, ids in groups.items():
            if team_id:
                vals = self._stamp_vals(Team.browse(team_id), backfilled_at=now)
                resolved += len(ids)
            else:
                vals = {"ordering_backfilled_at": now}
            Request.browse(ids).write(vals)

        _logger.info(
            "Ordering-team backfill: %s requests processed, %s resolved",
            len(records),
            resolved,
        )
        return len(records)

    def _member_team_map(self):
        """user id -> first team, in the order search(limit=1) would pick it.

        One pass over a handful of teams instead of one search per request.
        ``search([])`` and ``search([...], limit=1)`` share the model's
        _order, so ``setdefault`` reproduces the single-record lookup exactly.
        """
        mapping = {}
        for team in self.env["maintenance.team"].sudo().search([]):
            for member in team.member_ids:
                mapping.setdefault(member.id, team)
        return mapping

    def _category_preferred_team_members(self):
        """category id -> (preferred team, member id set), for categories
        that carry an override. Precomputed once per batch, same reasoning
        as ``_member_team_map``: a handful of categories, not one query per
        request.
        """
        mapping = {}
        Category = self.env["maintenance.request.category"].sudo()
        Team = self.env["maintenance.team"].sudo()
        for category in Category.search([("preferred_ordering_team_id", "!=", False)]):
            # search(), not a plain field read: a preferred team that has
            # since been archived must drop out here too, or the backfill
            # would stamp it while create() (via _preferred_category_team's
            # search) would not — exactly the divergence
            # test_archived_team_is_never_the_orderer exists to catch.
            team = Team.search([("id", "=", category.preferred_ordering_team_id.id)], limit=1)
            if not team:
                continue
            mapping[category.id] = (team, set(team.member_ids.ids))
        return mapping

    def _ad_team_map(self):
        """normalised AD unit -> team, for mapping rows whose team is active.

        Precomputed once per batch (a few dozen rows), same reasoning as
        ``_member_team_map``. search() on the team, not a field read, so a
        row pointing at an archived team drops out here exactly as it does in
        ``_ad_team`` on the create path.
        """
        mapping = {}
        Team = self.env["maintenance.team"].sudo()
        for unit in self.env["maintenance.ad.unit"].sudo().search([]):
            if not unit.name_normalized:
                continue
            team = Team.search([("id", "=", unit.team_id.id)], limit=1)
            if team:
                mapping[unit.name_normalized] = team
        return mapping

    def _user_ad_unit_map(self):
        """user id -> normalised AD unit, for users that have one.

        active_test=False: the creators of old requests may well have left
        the company since, and their AD unit is still the truthful answer for
        what they ordered back then.
        """
        rows = (
            self.env["res.users"]
            .sudo()
            .with_context(active_test=False)
            .search_read(
                [("ad_office_location", "!=", False)],
                ["ad_office_location"],
            )
        )
        mapping = {}
        for row in rows:
            normalized = normalize_ad_unit(row["ad_office_location"])
            # A whitespace-only value is "no AD unit", same as on the create
            # path where _ad_team returns early on an empty normalisation.
            if normalized:
                mapping[row["id"]] = normalized
        return mapping
