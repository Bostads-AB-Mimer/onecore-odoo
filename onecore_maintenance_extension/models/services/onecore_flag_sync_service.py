"""OneCore safety flags on maintenance requests: viktig kundinfo + spärr skadedjur.

Both badges have to render in the kanban overview (MIM-1959), so neither may be
computed on read - that would fire one OneCore call per card. Instead the flags
are snapshotted on the request (and on its tenant) by the write path and two
crons, the same shape as ManagementAreaService (MIM-1869).

Only records whose value actually changed are written. A run where nothing moved
issues no UPDATE at all, which is what keeps a 15-minute cadence cheap - and is
why there is no per-record "synced at" stamp: writing one would touch every open
request every run.
"""

import logging
import time

_logger = logging.getLogger(__name__)

# Seconds. A slow OneCore must not stall a cron run or a case creation.
LOOKUP_TIMEOUT = 15

# The caption Xpand uses. Matches the comparison in property-tree's residence
# view (ResidenceBasicInfo.tsx) - the block reason is a caption everywhere.
PEST_BLOCK_REASON = "SKADEDJUR"

# Per-worker cache of the blocked-rental-id set so a burst of case creations
# shares one OneCore call. Only the create path reads it; the cron always
# fetches fresh. Keyed on database: onecore_base_url is a per-database setting,
# so a worker serving several databases must not hand a staging answer to a
# production request.
PEST_SET_CACHE_TTL = 300  # seconds
_pest_set_cache = {}  # dbname -> (expires_at_monotonic, frozenset)


class OneCoreFlagSyncService:
    """Batch refresh of the two OneCore flags the kanban badges read."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------
    def is_configured(self):
        """Is OneCore reachable at all? Checked BEFORE constructing CoreApi:
        its __init__ POSTs for a token when none is persisted."""
        return bool(
            self.env["ir.config_parameter"].sudo().get_param("onecore_base_url")
        )

    def _api(self, api=None):
        return api or self.env["maintenance.request"].get_core_api()

    @staticmethod
    def get_rental_id(request):
        """OneCore's rentalId for the request's object, whatever its kind.

        Property- and building-level requests have no rental object and return
        False - they can never carry a rental block.
        """
        return (
            request.rental_property_id.rental_property_id
            or request.parking_space_id.rental_property_id
            or request.facility_id.rental_property_id
            or False
        )

    def open_requests(self):
        """Requests the badges are still shown on. Closed ones keep their last
        known value: the badge is about the object's current state, which stops
        being interesting once the case is done."""
        return (
            self.env["maintenance.request"]
            .sudo()
            .search([("closed_date", "=", False), ("archive", "=", False)])
        )

    @staticmethod
    def _apply(records, field, to_set, to_clear):
        """Two grouped writes, and none at all when nothing changed.

        skip_change_tracking: a flag flip must not post a chatter note
        (MIM-1959 decision 3) and one message_post per record would be slow.
        """
        model = records.browse([])
        if to_set:
            model.browse(to_set).with_context(skip_change_tracking=True).write(
                {field: True}
            )
        if to_clear:
            model.browse(to_clear).with_context(skip_change_tracking=True).write(
                {field: False}
            )
        return len(to_set) + len(to_clear)

    # ------------------------------------------------------------------
    # Spärr skadedjur
    # ------------------------------------------------------------------
    def fetch_pest_blocked_rental_ids(self, api=None):
        """Every rental id with an active SKADEDJUR block, as a set.

        Raises on failure and on a missing SKADEDJUR caption. An empty set is
        indistinguishable from "nothing is blocked", so a partial or
        accidentally-empty answer would clear the badge on genuinely blocked
        objects. All-or-nothing, like ManagementAreaService.build_property_map.
        """
        api = self._api(api)
        captions = api.fetch_block_reason_captions(timeout=LOOKUP_TIMEOUT)
        if PEST_BLOCK_REASON not in captions:
            raise ValueError(
                "OneCore does not know the block reason %s (got %s); refusing "
                "to clear the pest flag on every request"
                % (PEST_BLOCK_REASON, captions)
            )
        rental_ids = api.fetch_pest_blocked_rental_ids(
            block_reason=PEST_BLOCK_REASON, timeout=LOOKUP_TIMEOUT
        )
        return {rental_id for rental_id in (rental_ids or []) if rental_id}

    def sync_pest_control(self, api=None):
        """Refresh requires_pest_control on every open request.

        Returns the number of requests whose value changed, or 0 when OneCore
        could not be asked - in which case nothing is written and the last
        known values stand.
        """
        if not self.is_configured():
            _logger.info("Pest-control sync skipped: onecore_base_url is not set")
            return 0

        try:
            blocked = self.fetch_pest_blocked_rental_ids(api=api)
        except Exception as err:  # network, auth, caption rename
            _logger.warning("Pest-control sync skipped: %s", err)
            return 0

        requests = self.open_requests()
        to_set, to_clear = [], []
        for record in requests:
            rental_id = self.get_rental_id(record)
            desired = bool(rental_id) and rental_id in blocked
            if desired and not record.requires_pest_control:
                to_set.append(record.id)
            elif not desired and record.requires_pest_control:
                to_clear.append(record.id)

        changed = self._apply(requests, "requires_pest_control", to_set, to_clear)
        _logger.info(
            "Pest-control sync: %s blocked rental ids, %s open requests, "
            "%s set, %s cleared",
            len(blocked),
            len(requests),
            len(to_set),
            len(to_clear),
        )
        return changed
