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

# A failure must stop being believed sooner than a success: while OneCore is
# down, a burst of case creations should pay the timeout once per minute, not
# once per case - but it must not go on believing "down" for as long as it
# would have believed a real answer.
PEST_SET_FAILURE_TTL = 60  # seconds

_PEST_SET_FAILURE = object()  # sentinel: "recently failed", distinct from a set

_pest_set_cache = {}  # dbname -> (expires_at_monotonic, frozenset | _PEST_SET_FAILURE)

# Codes per /v1/contacts/batch call. The endpoint takes a repeated ?code=
# param, so the practical ceiling is URL length, not a documented limit.
CONTACT_BATCH_SIZE = 200


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
    def fetch_pest_blocked_rental_ids(self, api=None, verify_reason=True):
        """Every rental id with an active SKADEDJUR block, as a set.

        Raises on failure, on a ``None`` payload, and (when ``verify_reason``)
        on a missing SKADEDJUR caption. All-or-nothing, like
        ManagementAreaService.build_property_map: a genuinely empty list is a
        valid "nothing is blocked" answer and must NOT raise, but ``None`` -
        which ``CoreApi._get_json`` returns for a 200 whose body lacks
        ``content`` - must never be silently coerced into "nothing is
        blocked", or it would clear the badge on every request.

        ``verify_reason=False`` skips the block-reason-captions call. That
        guard exists only to stop an estate-wide clear when SKADEDJUR has been
        renamed upstream in Xpand; a caller that can only ever SET the flag on
        one record (the create path) can never clear anything, so the guard
        buys it nothing and would cost a second 15-second call. The cron must
        keep the guard and therefore never passes this.
        """
        api = self._api(api)
        if verify_reason:
            captions = api.fetch_block_reason_captions(timeout=LOOKUP_TIMEOUT)
            if PEST_BLOCK_REASON not in captions:
                raise ValueError(
                    "OneCore does not know the block reason %s (got %s); "
                    "refusing to clear the pest flag on every request"
                    % (PEST_BLOCK_REASON, captions)
                )
        rental_ids = api.fetch_pest_blocked_rental_ids(
            block_reason=PEST_BLOCK_REASON, timeout=LOOKUP_TIMEOUT
        )
        if rental_ids is None:
            raise ValueError(
                "OneCore returned no content for the pest-blocked rental ids "
                "lookup; refusing to treat that as an empty set"
            )
        return {rental_id for rental_id in rental_ids if rental_id}

    def cached_pest_blocked_rental_ids(self, api=None):
        """TTL-cached blocked set, for the create path only.

        A burst of case creations shares one OneCore call. The cron must never
        use this: a stale set is harmless for one new case, but a run that
        clears badges across the estate has to see current truth.

        Skips the caption guard (``verify_reason=False``) since a single
        create can only ever set the flag, never clear one - see
        ``fetch_pest_blocked_rental_ids``.

        A failure is cached too, for the much shorter ``PEST_SET_FAILURE_TTL``:
        while OneCore is down, a burst of creations should pay the timeout
        once, not once per case. Raises ``LookupError`` when a recent failure
        is still within its TTL, and re-raises the original error on a fresh
        failure - callers (``populate_pest_control``) are expected to catch
        both and never let them reach the caller of ``create()``.
        """
        key = self.env.cr.dbname
        cached = _pest_set_cache.get(key)
        if cached and time.monotonic() < cached[0]:
            if cached[1] is _PEST_SET_FAILURE:
                raise LookupError(
                    "Pest-blocked lookup failed recently; not retrying yet"
                )
            return cached[1]

        try:
            blocked = frozenset(
                self.fetch_pest_blocked_rental_ids(api=api, verify_reason=False)
            )
        except Exception:
            _pest_set_cache[key] = (
                time.monotonic() + PEST_SET_FAILURE_TTL,
                _PEST_SET_FAILURE,
            )
            raise

        _pest_set_cache[key] = (time.monotonic() + PEST_SET_CACHE_TTL, blocked)
        return blocked

    def populate_pest_control(self, request):
        """Stamp the pest flag on a freshly created request.

        Best effort, and never raises: OneCore being unreachable must not stop
        a handläggare - or an inbound mimer.nu request - from creating a case.
        The flag stays False and the next cron run heals it.
        """
        if not self.is_configured():
            return False
        rental_id = self.get_rental_id(request)
        if not rental_id:
            return False

        try:
            blocked = self.cached_pest_blocked_rental_ids()
        except Exception as err:
            _logger.warning(
                "Could not fetch pest blocks for new request %s: %s",
                request.id,
                err,
            )
            return False

        if rental_id not in blocked:
            return False

        request.sudo().with_context(skip_change_tracking=True).write(
            {"requires_pest_control": True}
        )
        return True

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

    # ------------------------------------------------------------------
    # Viktig kundinfo
    # ------------------------------------------------------------------
    def fetch_special_attention(self, contact_codes, api=None):
        """contact_code -> specialAttention, for the codes OneCore answered for.

        Codes missing from the result are missing on purpose: "unknown" must
        never be written as False. A chunk that fails is logged and skipped -
        unlike the pest set, each code stands on its own, so a partial answer
        is correct rather than dangerous.
        """
        codes = list(contact_codes)
        if not codes:
            return {}

        api = self._api(api)
        flags = {}
        for start in range(0, len(codes), CONTACT_BATCH_SIZE):
            chunk = codes[start : start + CONTACT_BATCH_SIZE]
            try:
                content = api.fetch_contacts_batch(chunk, timeout=LOOKUP_TIMEOUT)
            except Exception as err:
                _logger.warning(
                    "Viktig kundinfo: could not fetch %s contacts (from %s): %s",
                    len(chunk),
                    chunk[0],
                    err,
                )
                continue
            for contact in content or []:
                code = contact.get("contactCode")
                if not code:
                    continue
                communication = contact.get("communication") or {}
                flags[code] = bool(communication.get("specialAttention"))
        return flags

    def sync_special_attention(self, api=None):
        """Refresh special_attention on the tenants of every open request.

        The flag is snapshotted from the tenant payload when the case is
        created; without this it would never pick up a change made in Xpand
        afterwards. Returns the number of tenant records changed.
        """
        if not self.is_configured():
            _logger.info("Viktig kundinfo-sync skipped: onecore_base_url is not set")
            return 0

        tenants = self.open_requests().mapped("tenant_id")
        codes = sorted({t.contact_code for t in tenants if t.contact_code})
        if not codes:
            return 0

        flags = self.fetch_special_attention(codes, api=api)

        to_set, to_clear = [], []
        for tenant in tenants:
            desired = flags.get(tenant.contact_code)
            if desired is None:
                continue
            if desired and not tenant.special_attention:
                to_set.append(tenant.id)
            elif not desired and tenant.special_attention:
                to_clear.append(tenant.id)

        changed = self._apply(tenants, "special_attention", to_set, to_clear)
        _logger.info(
            "Viktig kundinfo-sync: %s codes asked, %s answered, %s set, " "%s cleared",
            len(codes),
            len(flags),
            len(to_set),
            len(to_clear),
        )
        return changed
