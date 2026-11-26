"""Outcomes on an ärende's components, sent to OneCore as component events.

A saved outcome only marks the row pending and triggers the sync cron, so no
HTTP call runs in the user's transaction. The cron sends each row with one
call, the event POST, and commits after each row. Core is idempotent on
(sourceType, sourceId, componentId, eventType), so sending a row again is safe.
"""

import logging
from datetime import timedelta

import pytz
import requests
from psycopg2.errors import SerializationFailure

from odoo import fields
from odoo.tools import mute_logger

from ....onecore_api import core_api
from .management_area_service import ManagementAreaService

_logger = logging.getLogger(__name__)

# The component event each outcome is sent as, keyed by the Odoo outcome.
# REPLACED and RENEWED are not sent from here, so they are not listed.
OUTCOME_EVENT_TYPES = {
    "REPAIRED": "REPAIRED",
    "REMEDIED": "REPAIRED",
    "NO_ACTION": "NO_ACTION",
}
SOURCE_TYPE = "WORK_ORDER"
OCCURRED_AT_TZ = pytz.timezone("Europe/Stockholm")

# (connect, read) seconds for the event POST, the one call per row. A row is
# started only while the run has ROW_BUDGET left, as ir.cron._commit_progress
# reports it: what remains of the MIN_TIME_PER_JOB (10 s) window from the
# start of the run. With 5 s, rows start during the first half of every run.
# The short read timeout is safe because core is idempotent: an event it
# saved after Odoo gave up comes back as the same event on the retry. A token
# fetch (on a 401, or when none is stored) runs on CoreApi's own, longer
# timeout, which the budget doesn't cover; it can make one run end later, but
# still well within limit_time_real_cron.
SEND_TIMEOUT = (2, 3)
ROW_BUDGET = sum(SEND_TIMEOUT)
# A failed row is sent again once this long has passed since its last try, so
# a run never retries the rows it just tried. Shorter than the cron interval.
RETRY_AFTER = timedelta(minutes=10)
# Characters of core's error text kept in sync_error
MAX_CORE_ERROR = 300

# Failed rows and rows pending past the grace period are sent by the cron,
# and an administrator can send them again if that doesn't help
IF_IT_STAYS = "Kontakta en administratör om märket ligger kvar."
RETRY_LATER = f"Utfallet skickas igen automatiskt. {IF_IT_STAYS}"
SENT_LATER = f"Utfallet skickas automatiskt. {IF_IT_STAYS}"
CONTACT_ADMIN = (
    "Kontakta en administratör. När felet är rättat kan administratören skicka "
    "utfallet igen från ärendet."
)


class ComponentEventSyncService:
    """Sends queued component outcomes to OneCore and stores the result."""

    def __init__(self, env):
        self.env = env
        self._api = None

    @staticmethod
    def event_type(component):
        """The event type the component's outcome is sent as, or None."""
        return OUTCOME_EVENT_TYPES.get(component.outcome)

    @staticmethod
    def status_text(component):
        """Why the component's outcome isn't in OneCore and what to do next,
        for the ärende's form: the stored error of a failed or rejected row,
        or a line for a row still waiting to be sent."""
        work_order = ComponentEventSyncService._work_order(component)
        name = component._summary_name()
        if component.sync_state in ("failed", "rejected") and component.sync_error:
            return component.sync_error
        if component.sync_state == "rejected":
            return (
                f"{work_order}: OneCore tog inte emot utfallet för {name}. "
                f"{CONTACT_ADMIN}"
            )
        if component.sync_state == "failed":
            return (
                f"{work_order}: Utfallet för {name} har inte kommit fram till "
                f"OneCore. {RETRY_LATER}"
            )
        return (
            f"{work_order}: Utfallet för {name} väntar på att skickas till "
            f"OneCore. {SENT_LATER}"
        )

    def sync_queued(self):
        """Send the pending rows, then the failed rows due for a retry, one
        row at a time. Returns the number of rows handled."""
        if not ManagementAreaService(self.env).is_configured():
            _logger.info("Component event sync skipped: onecore_base_url is not set")
            return 0
        Component = self.env["maintenance.request.component"].sudo()
        queue = self._queue(Component)
        if not queue:
            return 0

        Cron = self.env["ir.cron"]
        time_left = Cron._commit_progress(remaining=len(queue))
        handled = 0
        for component_id in queue:
            if time_left < ROW_BUDGET:
                _logger.info(
                    "Component event sync: out of time, %s rows left for the next run",
                    len(queue) - handled,
                )
                break
            # Browsed one at a time, so each row is read in its own transaction
            self._sync_one(Component.browse(component_id))
            handled += 1
            time_left = Cron._commit_progress(1)
        return handled

    def _queue(self, Component):
        """Ids of the rows to send: pending first, then failed rows not tried
        within RETRY_AFTER, least recently tried first. Rows on archived
        ärenden are included."""
        pending = Component.search([("sync_state", "=", "pending")], order="id")
        failed = Component.search(
            [
                ("sync_state", "=", "failed"),
                "|",
                ("sync_attempted_at", "=", False),
                ("sync_attempted_at", "<", fields.Datetime.now() - RETRY_AFTER),
            ],
            order="sync_attempted_at, id",
        )
        return pending.ids + failed.ids

    def _sync_one(self, component):
        # Deleted since the queue was read, e.g. with its ärende
        component = component.exists()
        if not component:
            return
        work_order = self._work_order(component)
        event_type = self.event_type(component)
        if not event_type:
            # Queued by hand with an outcome that isn't sent from here
            self._store(component, {"sync_state": False}, work_order, "cleared")
            return
        payload, error = self._payload(component, event_type, work_order)
        if error:
            values = {"sync_state": "rejected", "sync_error": error}
            status = "rejected before sending"
        else:
            values, status = self._send(component, payload, work_order)
        values["sync_attempted_at"] = fields.Datetime.now()
        self._store(component, values, work_order, status)

    @staticmethod
    def _work_order(component):
        # Imported here: the wizard module imports this package
        from ..maintenance_time_report_wizard import WORK_ORDER_PREFIX

        return f"{WORK_ORDER_PREFIX}{component.maintenance_request_id.id}"

    def _core(self):
        """The CoreApi client, made on first use. Making it can fetch a token,
        so call this where requests.RequestException is handled."""
        if self._api is None:
            self._api = core_api.CoreApi(self.env)
        return self._api

    @staticmethod
    def _payload(component, event_type, work_order):
        """(payload, None), or (None, error) when the row can't be sent."""
        name = component._summary_name()
        actor = (component.outcome_user_id.login or "").strip()
        if not actor:
            return None, (
                f"{work_order}: Utfallet för {name} saknar vem som registrerade det "
                f"och kan inte skickas till OneCore. {CONTACT_ADMIN}"
            )
        moment = (
            component.maintenance_request_id.performed_date
            or component.outcome_recorded_at
        )
        if not moment:
            return None, (
                f"{work_order}: Utfallet för {name} saknar datum och kan inte "
                f"skickas till OneCore. {CONTACT_ADMIN}"
            )
        occurred_at = pytz.utc.localize(moment).astimezone(OCCURRED_AT_TZ).date()
        return {
            "eventType": event_type,
            "occurredAt": occurred_at.isoformat(),
            "sourceType": SOURCE_TYPE,
            "sourceId": work_order,
            "actor": actor,
            "note": component.outcome_note or None,
        }, None

    def _send(self, component, payload, work_order):
        """POST the event. Returns (values to store, status for the log)."""
        try:
            response = self._core().create_component_event(
                component.onecore_component_id, payload, timeout=SEND_TIMEOUT
            )
        except requests.RequestException as err:
            return {
                "sync_state": "failed",
                "sync_error": f"{work_order}: OneCore svarade inte. {RETRY_LATER}",
            }, f"failed ({type(err).__name__})"

        status_code = response.status_code
        body = self._json(response)
        if status_code in (200, 201):
            content = body.get("content") if isinstance(body, dict) else None
            event_id = content.get("id") if isinstance(content, dict) else None
            if event_id and isinstance(event_id, str):
                return {
                    "sync_state": "synced",
                    "core_event_id": event_id,
                }, f"synced (HTTP {status_code})"
            return {
                "sync_state": "failed",
                "sync_error": (
                    f"{work_order}: OneCore bekräftade inte utfallet "
                    f"(HTTP {status_code} utan id). {RETRY_LATER}"
                ),
            }, f"failed (HTTP {status_code} without content.id)"
        # Only core's own answer, which is JSON, rejects the event: a 400 for
        # an event core won't take, a 404 for a component it doesn't have. A
        # 404 without JSON comes from a core that lacks the route and is
        # retried, as is every other answer.
        if status_code in (400, 404) and isinstance(body, dict):
            core_error = self._core_error(body, status_code)
            return {
                "sync_state": "rejected",
                "sync_error": (
                    f"{work_order}: OneCore tog inte emot utfallet för "
                    f"{component._summary_name()}: {core_error}. {CONTACT_ADMIN}"
                ),
            }, f"rejected (HTTP {status_code}: {core_error})"
        return {
            "sync_state": "failed",
            "sync_error": (
                f"{work_order}: OneCore kunde inte spara utfallet "
                f"(HTTP {status_code}). {RETRY_LATER}"
            ),
        }, f"failed (HTTP {status_code})"

    @staticmethod
    def _json(response):
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _core_error(body, status_code):
        """Core's error, a string or a list of zod issues, as one line."""
        error = body.get("error")
        if isinstance(error, list):
            error = "; ".join(_issue_text(issue) for issue in error)
        error = str(error or "").strip()
        return (error or f"HTTP {status_code}")[:MAX_CORE_ERROR]

    def _store(self, component, values, work_order, status):
        """Write the result. A change or deletion another transaction
        committed during the send fails the write as a serialization failure
        (the cron's transaction is REPEATABLE READ), which leaves the row as
        that transaction left it."""
        values = {
            "sync_error": False,
            "core_event_id": False,
            "sync_attempted_at": False,
            **values,
        }
        try:
            with mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                component.write(values)
        except SerializationFailure:
            _logger.info(
                "Component event sync: row %s (%s) changed concurrently; "
                "result not stored",
                component.id,
                work_order,
            )
            return
        log = _logger.warning if values["sync_state"] in ("failed", "rejected") else _logger.info
        log("Component event sync: row %s (%s) %s", component.id, work_order, status)


def _issue_text(issue):
    """'actor: String must contain at least 1 character(s)' from a zod issue."""
    if not isinstance(issue, dict):
        return str(issue)
    path = ".".join(str(part) for part in issue.get("path") or [])
    message = str(issue.get("message") or "")
    return f"{path}: {message}" if path else message
