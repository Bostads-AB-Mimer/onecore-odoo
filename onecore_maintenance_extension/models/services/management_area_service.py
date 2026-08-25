"""Management areas on maintenance requests: distrikt + kvartersvärdsområde.

OneCore owns the hierarchy  property -> kvv area (kvartersvärdsområde)
-> cost center (distrikt)  (onecore_property_kvv_area / onecore_kvv_area /
onecore_cost_center). Odoo snapshots the codes and names on the request so
they can be shown ("Tillhör distrikt"), grouped, and used to pair a team
("Tilldela resursgrupp").

Write path only: create(), the button and the backfill cron. Never on read
(MIM-1869 removed sync HTTP from the maintenance.request read path).
"""

import logging
import time

from odoo import fields

_logger = logging.getLogger(__name__)

# Seconds. A slow OneCore must not stall request creation or the button.
LOOKUP_TIMEOUT = 5

# Per-worker cache so the form preview (onchange) and the create() snapshot
# right after it share one OneCore call, and so picking between search hits on
# the same property is free. Worst-case staleness = TTL; a property changes kvv
# area very rarely. Keyed on (database, property_code): onecore_base_url is a
# per-database setting, so a worker serving several databases must not hand a
# staging answer to a production request.
DISTRICT_CACHE_TTL = 300  # seconds
_district_cache = {}  # (dbname, property_code) -> (expires_at_monotonic, values | None)


class ManagementAreaService:
    """Lookup, snapshot and team pairing of distrikt / kvartersvärdsområde."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Property code — the join key towards OneCore
    # ------------------------------------------------------------------
    @staticmethod
    def get_property_code(request):
        """Property code of the request's location, whatever the object type.

        Same fallback order as the historical open_time_report chain, plus
        the building's property for building-level requests.
        """
        return (
            request.estate_code
            or request.parking_space_property_code
            or request.facility_property_code
            or request.property_code
            or request.building_property_code
            or False
        )

    @staticmethod
    def get_property_code_from_options(record):
        """Property code from the transient search options, i.e. before the
        request is saved and the snapshot records exist. Same order as
        get_property_code()."""
        return (
            record.rental_property_option_id.estate_code
            or record.parking_space_option_id.property_code
            or record.facility_option_id.property_code
            or record.property_option_id.code
            or record.building_option_id.property_code
            or False
        )

    # ------------------------------------------------------------------
    # OneCore lookup
    # ------------------------------------------------------------------
    def is_configured(self):
        """Is OneCore reachable at all? Checked BEFORE constructing CoreApi:
        its __init__ POSTs for a token when none is persisted."""
        return bool(
            self.env["ir.config_parameter"].sudo().get_param("onecore_base_url")
        )

    @staticmethod
    def normalize(payload):
        """OneCore ``{kvvArea, costCenter, ...}`` -> request values, or None."""
        if not payload:
            return None
        kvv_area = payload.get("kvvArea") or {}
        cost_center = payload.get("costCenter") or {}
        if not kvv_area.get("code") and not cost_center.get("code"):
            return None
        return {
            "kvv_area_code": kvv_area.get("code") or False,
            "kvv_area_name": kvv_area.get("name") or False,
            "cost_center_code": cost_center.get("code") or False,
            "cost_center_name": cost_center.get("name") or False,
        }

    def fetch_for_property(self, property_code, api=None):
        """Ask OneCore for the management area of ``property_code``.

        Returns ``(ok, values)``:
        - ``ok=False``: OneCore could not be asked (no property code, not
          configured, HTTP/parse error). Callers must NOT stamp
          ``management_area_lookup_at`` — the backfill cron retries later.
        - ``ok=True``: answered; ``values`` is a dict, or None when the
          property has no management-area link.
        """
        if not property_code or not self.is_configured():
            return False, None

        cache_key = (self.env.cr.dbname, property_code)
        cached = _district_cache.get(cache_key)
        if cached and time.monotonic() < cached[0]:
            return True, cached[1]

        try:
            api = api or self.env["maintenance.request"].get_core_api()
            payload = api.fetch_kvv_area_for_property(
                property_code, timeout=LOOKUP_TIMEOUT
            )
        except Exception as err:  # network, auth, JSON — never break the caller
            _logger.warning(
                "Could not fetch management area for property %s: %s",
                property_code,
                err,
            )
            return False, None

        values = self.normalize(payload)
        # Cache misses too: a property without a kvv link stays without one.
        _district_cache[cache_key] = (
            time.monotonic() + DISTRICT_CACHE_TTL,
            values,
        )
        return True, values

    def preview(self, record):
        """Show distrikt/kvartersvärdsområde on the form before the request is
        saved (onchange), and prefill Resursgrupp from the district.

        Only fills the in-memory record — create() does the authoritative
        lookup, hitting the same cache.

        The prefill exists because maintenance_team_id is required to save:
        without it the user has to guess a team at creation and correct it with
        the button afterwards. Never overrides a team the user (or a caller)
        picked — a Vitvaru- or Skadedjursärende must keep its team.

        Re-runs on every option change: picking a second property in the same
        unsaved form must not keep the first property's distrikt, nor the team
        prefilled from it.
        """
        property_code = self.get_property_code_from_options(record)
        if not property_code:
            return False
        ok, values = self.fetch_for_property(property_code)
        if not ok or not values:
            return False
        if values.get("cost_center_code") == record.cost_center_code and values.get(
            "kvv_area_code"
        ) == record.kvv_area_code:
            return False

        previous_code = record.cost_center_code
        for field, value in values.items():
            record[field] = value

        team = record.maintenance_team_id
        # Replace a team only when it is ours to replace: empty, or the one we
        # prefilled from the district the user just navigated away from.
        if not team or (previous_code and team.cost_center_code == previous_code):
            new_team = self.find_team_for_cost_center(values.get("cost_center_code"))
            if new_team:
                record.maintenance_team_id = new_team
        return True

    def populate(self, request, force=False, api=None):
        """Snapshot distrikt/kvv area on ``request``.

        Returns True when values were written. Requests that already carry a
        cost center are skipped unless ``force`` (the button uses force to
        retry legacy requests).
        """
        request.ensure_one()
        if request.cost_center_code and not force:
            return False
        ok, values = self.fetch_for_property(self.get_property_code(request), api=api)
        if not ok:
            return False
        vals = dict(values or {})
        vals["management_area_lookup_at"] = fields.Datetime.now()
        # sudo: creators over RPC (mimer.nu) and contractors must not be
        # blocked by record rules when the snapshot is written.
        request.sudo().write(vals)
        return bool(values)

    # ------------------------------------------------------------------
    # Team pairing — "Tilldela resursgrupp"
    # ------------------------------------------------------------------
    def find_team_for_cost_center(self, cost_center_code):
        """Active team whose cost_center_code matches (never by name)."""
        if not cost_center_code:
            return self.env["maintenance.team"]
        teams = (
            self.env["maintenance.team"]
            .sudo()
            .search([("cost_center_code", "=", cost_center_code)])
        )
        if len(teams) > 1:
            _logger.warning(
                "Several maintenance teams share cost center %s (%s); using the first",
                cost_center_code,
                teams.ids,
            )
        return teams[:1]

    def assign_team(self, request):
        """Pair the request with its district's team.

        Returns ``{"team", "changed", "error"}``. Problems are reported as an
        ``error`` message instead of raised, so a district fetched on the way
        is kept (an exception would roll the whole transaction back).
        """
        request.ensure_one()
        if not request.cost_center_code:
            self.populate(request, force=True)

        no_team = self.env["maintenance.team"]
        if not request.cost_center_code:
            return {
                "team": no_team,
                "changed": False,
                "error": "Ärendet saknar distrikt och kunde inte slås upp i OneCore.",
            }

        team = self.find_team_for_cost_center(request.cost_center_code)
        if not team:
            return {
                "team": no_team,
                "changed": False,
                "error": (
                    "Ingen resursgrupp är kopplad till distrikt %s. "
                    "Ange kostnadsställe på resursgruppen."
                )
                % (request.cost_center_name or request.cost_center_code),
            }

        if request.maintenance_team_id == team:
            return {"team": team, "changed": False, "error": None}

        vals = {"maintenance_team_id": team.id}
        if request.user_id and request.user_id not in team.member_ids:
            # Same rule as _onchange_maintenance_team_id: an assignee outside
            # the new team is cleared (write() then bounces the stage back to
            # "Väntar på handläggning").
            vals["user_id"] = False
        request.write(vals)
        return {"team": team, "changed": True, "error": None}

    # ------------------------------------------------------------------
    # Kvv-area master sync — feeds "Nuvarande kvartersvärd" + distriktschef
    # ------------------------------------------------------------------
    @staticmethod
    def _user_summary_vals(prefix, summary):
        """OneCore KeycloakUserSummary -> {prefix}_name/_email/_phone.

        Users OneCore cannot resolve (not in a group carrying the
        property-manager role) arrive as None and become False.
        """
        summary = summary or {}
        name = " ".join(
            part
            for part in (summary.get("firstName"), summary.get("lastName"))
            if part
        )
        return {
            f"{prefix}_name": name or False,
            f"{prefix}_email": summary.get("email") or False,
            f"{prefix}_phone": summary.get("mobilePhone") or False,
        }

    def sync_kvv_areas(self, api=None):
        """Refresh the maintenance.kvv.area master from GET /kvv-areas.

        Rows are matched on code and only written when something actually
        changed (~33 areas). Areas that disappear from OneCore are kept:
        old requests still reference their code. Returns the number of
        created/updated rows, or 0 when OneCore could not be asked.
        """
        if not self.is_configured():
            return 0
        try:
            api = api or self.env["maintenance.request"].get_core_api()
            areas = api.fetch_kvv_areas() or []
        except Exception as err:
            _logger.warning("Could not sync kvv areas from OneCore: %s", err)
            return 0

        Master = self.env["maintenance.kvv.area"].sudo()
        existing = {record.code: record for record in Master.search([])}
        now = fields.Datetime.now()
        synced = 0
        for area in areas:
            code = area.get("code")
            if not code:
                continue
            cost_center = area.get("costCenter") or {}
            vals = {
                "name": area.get("name") or False,
                "cost_center_code": cost_center.get("code") or False,
                "cost_center_name": cost_center.get("name") or False,
                **self._user_summary_vals("responsible", area.get("responsible")),
            }
            vals["responsible_keycloak_id"] = (area.get("responsible") or {}).get(
                "id"
            ) or False
            record = existing.get(code)
            if record:
                changed = {
                    field: value
                    for field, value in vals.items()
                    if record[field] != value
                }
                if changed:
                    changed["synced_at"] = now
                    record.write(changed)
                    synced += 1
            else:
                Master.create({**vals, "code": code, "synced_at": now})
                synced += 1
        if synced:
            _logger.info("Kvv-area sync: %s areas created/updated", synced)
        return synced

    # ------------------------------------------------------------------
    # Cost-center master sync — feeds "Distriktschef"
    # ------------------------------------------------------------------
    def sync_cost_centers(self, api=None):
        """Refresh maintenance.cost.center from the cost-center trees.

        lead/deputy are hydrated Keycloak users on the tree root, so five
        tree calls cover every district. Runs nightly: a distriktschef changes
        far less often than a kvartersvärd, and OneCore caches the trees.
        Returns the number of created/updated rows.
        """
        if not self.is_configured():
            return 0
        try:
            api = api or self.env["maintenance.request"].get_core_api()
            cost_centers = api.fetch_cost_centers() or []
            trees = [api.fetch_cost_center_tree(cc["id"]) or {} for cc in cost_centers]
        except Exception as err:
            _logger.warning("Could not sync cost centers from OneCore: %s", err)
            return 0

        Master = self.env["maintenance.cost.center"].sudo()
        existing = {record.code: record for record in Master.search([])}
        now = fields.Datetime.now()
        synced = 0
        for tree in trees:
            code = tree.get("code")
            if not code:
                continue
            vals = {
                "name": tree.get("name") or False,
                **self._user_summary_vals("lead", tree.get("lead")),
                **self._user_summary_vals("deputy", tree.get("deputy")),
            }
            record = existing.get(code)
            if record:
                changed = {
                    field: value
                    for field, value in vals.items()
                    if record[field] != value
                }
                if changed:
                    changed["synced_at"] = now
                    record.write(changed)
                    synced += 1
            else:
                Master.create({**vals, "code": code, "synced_at": now})
                synced += 1
        if synced:
            _logger.info("Cost-center sync: %s districts created/updated", synced)
        return synced

    # ------------------------------------------------------------------
    # Backfill (cron) — display only, never touches team/resource
    # ------------------------------------------------------------------
    def backfill_batch(self, limit=1000, api=None):
        """Stamp up to ``limit`` requests that have no cost center and were
        never successfully looked up. Returns the number processed.

        Uses the cost-center trees (a handful of calls) instead of one call
        per property. Unresolvable requests (no property code, property not
        in any tree) are stamped too so they are not retried every run; the
        button can still force a retry on demand.
        """
        Request = self.env["maintenance.request"].sudo()
        records = Request.search(
            [
                ("cost_center_code", "=", False),
                ("management_area_lookup_at", "=", False),
            ],
            order="id desc",
            limit=limit,
        )
        if not records:
            return 0
        if not self.is_configured():
            _logger.info("Management-area backfill skipped: onecore_base_url is not set")
            return 0

        try:
            api = api or Request.get_core_api()
            property_map = self.build_property_map(api)
        except Exception as err:
            _logger.warning(
                "Management-area backfill: could not build the property map: %s", err
            )
            return 0
        if not property_map:
            _logger.warning(
                "Management-area backfill: OneCore returned no cost-center trees; "
                "nothing stamped"
            )
            return 0

        now = fields.Datetime.now()
        groups = {}  # values (as sorted tuple) -> request ids
        for record in records:
            property_code = self.get_property_code(record)
            values = property_map.get(property_code) if property_code else None
            key = tuple(sorted(values.items())) if values else ()
            groups.setdefault(key, []).append(record.id)

        resolved = 0
        for key, ids in groups.items():
            vals = dict(key)
            vals["management_area_lookup_at"] = now
            Request.browse(ids).write(vals)
            if key:
                resolved += len(ids)

        _logger.info(
            "Management-area backfill: %s requests processed, %s resolved",
            len(records),
            resolved,
        )
        return len(records)

    @staticmethod
    def build_property_map(api):
        """property_code -> request values, from GET /cost-centers/{id}/tree.

        Raises when a tree cannot be fetched: a partial map would make the
        caller stamp that district's requests as "looked up", excluding them
        from every future run. All-or-nothing is cheap here — five calls.
        """
        mapping = {}
        for cost_center in api.fetch_cost_centers() or []:
            tree = api.fetch_cost_center_tree(cost_center["id"])
            if not tree:
                raise ValueError(
                    f"Empty cost-center tree for {cost_center.get('code')}"
                )
            cost_center_code = tree.get("code") or cost_center.get("code") or False
            cost_center_name = tree.get("name") or cost_center.get("name") or False
            for area in tree.get("kvvAreas") or []:
                for prop in area.get("properties") or []:
                    code = prop.get("code")
                    if not code:
                        continue
                    mapping[code] = {
                        "kvv_area_code": area.get("code") or False,
                        "kvv_area_name": area.get("name") or False,
                        "cost_center_code": cost_center_code,
                        "cost_center_name": cost_center_name,
                    }
        return mapping
