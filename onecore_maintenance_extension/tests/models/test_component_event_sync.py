"""Outcomes sent to OneCore as component events: the queue on save, the
payload, how core's answers are stored, the cron's retries and an
administrator's resend.

OneCore is never called: requests.request, requests.get and requests.post are
faked for the whole test, and the event route answers what each test scripts.
"""

import json
import logging
from datetime import datetime, timedelta
from unittest.mock import patch

import requests
from lxml import etree
from psycopg2.errors import SerializationFailure

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_cron import MIN_TIME_PER_JOB
from odoo.addons.onecore_api import core_api

from ...models.services.component_event_sync_service import (
    RETRY_AFTER,
    ROW_BUDGET,
    SEND_TIMEOUT,
)
from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_team,
)
from .test_maintenance_request_component import _link_vals
from .test_mark_done import MarkDoneCase, _surface_vals

BASE_URL = "https://core.test"
EVENT_ID = "6f0c4a52-3d3e-4c8e-9a51-1f2d3c4b5a60"
SERVICE_LOGGER = (
    "odoo.addons.onecore_maintenance_extension.models.services."
    "component_event_sync_service"
)
# What a failed or long-pending row tells the user to do if the badge stays
IF_IT_STAYS = "Kontakta en administratör om märket ligger kvar."


def _response(status, body=None, text=""):
    response = requests.Response()
    response.status_code = status
    if body is not None:
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/json"
    else:
        response._content = text.encode()
        response.headers["Content-Type"] = "text/plain"
    return response


def _event(status=201, event_id=EVENT_ID):
    """Core's answer to a created (201) or repeated (200) event."""
    return _response(
        status,
        {
            "content": {
                "id": event_id,
                "componentId": "0b9d8c1e-2f3a-4b5c-8d7e-6f5a4b3c2d1e",
                "eventType": "REPAIRED",
                "occurredAt": "2026-11-25",
                "sourceType": "WORK_ORDER",
                "sourceId": "od-1",
                "relatedComponentId": None,
                "actor": "someone",
                "note": None,
                "createdAt": "2026-11-25T10:00:00.000Z",
            },
            "metadata": {},
        },
    )


class ComponentEventCase(MarkDoneCase):
    def setUp(self):
        super().setUp()
        self.cron = self.env.ref(
            "onecore_maintenance_extension.ir_cron_sync_component_events"
        )
        self.calls = []
        # What the event route and the token route answer in turn; after
        # that the event is created and a new token is issued
        self.answers = []
        self.token_answers = []
        self.startPatcher(
            patch.object(core_api.requests, "request", side_effect=self._fake_request)
        )
        self.startPatcher(
            patch.object(core_api.requests, "post", side_effect=self._fake_post)
        )
        self.startPatcher(
            patch.object(core_api.requests, "get", side_effect=self._fake_get)
        )

    # -- fake OneCore -------------------------------------------------------
    def _fake_request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not url.endswith("/events"):
            raise requests.ConnectionError(f"No fake OneCore route for {url}")
        return self._answer(self.answers, _event)

    @staticmethod
    def _answer(scripted, default):
        answer = scripted.pop(0) if scripted else default()
        if callable(answer):
            answer = answer()
        if isinstance(answer, Exception):
            raise answer
        return answer

    def _fake_post(self, url, **kwargs):
        """The token fetch (requests.post in CoreApi): `token_answers` in
        turn, a new token after that."""
        self.calls.append({"method": "POST", "url": url, **kwargs})
        if url.endswith("/auth/generateToken"):
            return self._answer(
                self.token_answers, lambda: _response(200, {"token": "refreshed-token"})
            )
        raise requests.ConnectionError(f"No fake OneCore route for {url}")

    def _fake_get(self, url, **kwargs):
        """requests.get (CoreApi's parallel calls): no route is faked."""
        self.calls.append({"method": "GET", "url": url, **kwargs})
        raise requests.ConnectionError(f"No fake OneCore route for {url}")

    def _event_calls(self):
        return [call for call in self.calls if call["url"].endswith("/events")]

    def _token_calls(self):
        return [call for call in self.calls if call["url"].endswith("/generateToken")]

    # -- helpers ------------------------------------------------------------
    def _configure_core(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("onecore_base_url", BASE_URL)
        params.set_param("onecore_api_token", "test-token")

    def _sync(self, *answers, time_left=(), configure=True):
        """Run the cron's body once, with the event route answering `answers`
        in turn (201 after that). `time_left` is what each _commit_progress
        returns (plenty after that). Returns the _commit_progress mock."""
        if configure:
            self._configure_core()
        self.answers = list(answers)
        times = iter(time_left)
        with patch.object(
            type(self.env["ir.cron"]),
            "_commit_progress",
            side_effect=lambda *args, **kwargs: next(times, 1000.0),
        ) as commit:
            self.env["maintenance.request.component"]._cron_sync_component_events()
        return commit

    def _triggers(self):
        return self.env["ir.cron.trigger"].search_count(
            [("cron_id", "=", self.cron.id)]
        )

    def _registered(self, *link_vals, outcome="REPAIRED", note="", user=None, **kwargs):
        """An ärende in Utförd whose components got `outcome` through
        Markera som utförd."""
        request = self._request(*(link_vals or (_link_vals(),)), **kwargs)
        self._register(request, self._answers(request, outcome, note), user=user)
        return self.env["maintenance.request"].browse(request.id)

    def _later(self, components):
        """As if the last try was long enough ago to retry."""
        components.write(
            {"sync_attempted_at": fields.Datetime.now() - RETRY_AFTER - timedelta(minutes=1)}
        )


@tagged("onecore")
class TestComponentEventQueue(ComponentEventCase):
    """Saving an outcome queues the row; nothing is sent in the save."""

    def test_registering_outcomes_queues_the_rows_and_triggers_the_cron(self):
        request = self._request(_link_vals(), _link_vals("comp-spis", "Spis"))
        triggers_before = self._triggers()

        self._register(request, self._answers(request, "REPAIRED"))

        self.assertEqual(request.stage_id, self.done_stage)
        self.assertEqual(request.component_ids.mapped("sync_state"), ["pending", "pending"])
        self.assertEqual(self._triggers(), triggers_before + 1)
        self.assertFalse(self._event_calls())

    def test_contractor_registering_outcomes_queues_the_rows(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        triggers_before = self._triggers()

        request = self._registered(
            outcome="NO_ACTION", user=contractor, maintenance_team_id=team.id
        )

        self.assertEqual(request.component_ids.sync_state, "pending")
        self.assertEqual(request.component_ids.outcome_user_id, contractor)
        self.assertEqual(self._triggers(), triggers_before + 1)

    def test_replaced_and_renewed_are_not_queued(self):
        request = self._request(_link_vals(), _surface_vals())
        fridge = request.component_ids.filtered(lambda c: c.component_name == "Frys")
        floor = request.component_ids - fridge
        triggers_before = self._triggers()

        self._register(
            request,
            [
                {"id": fridge.id, "outcome": "REPLACED", "note": ""},
                {"id": floor.id, "outcome": "RENEWED", "note": ""},
            ],
        )

        self.assertFalse(request.component_ids.filtered("sync_state"))
        self.assertEqual(self._triggers(), triggers_before)

    def test_superuser_writes_are_queued_too(self):
        request = self._request(_link_vals())

        request.component_ids.write({"outcome": "REPAIRED"})

        self.assertEqual(request.component_ids.sync_state, "pending")

    def test_a_multi_record_write_queues_each_changed_row_and_triggers_once(self):
        request = self._request(
            _link_vals(), _link_vals("comp-spis", "Spis"), _link_vals("comp-ugn", "Ugn")
        )
        components = request.component_ids.with_user(self.internal_user)
        fridge = components.filtered(lambda c: c.component_name == "Frys")
        fridge.write({"outcome": "REPAIRED"})
        self._sync()
        self.assertEqual(fridge.sync_state, "synced")
        triggers_before = self._triggers()

        components.write({"outcome": "REPAIRED"})

        self.assertEqual(fridge.sync_state, "synced")
        self.assertEqual(fridge.core_event_id, EVENT_ID)
        self.assertEqual(
            (components - fridge).mapped("sync_state"), ["pending", "pending"]
        )
        self.assertEqual(self._triggers(), triggers_before + 1)

    def test_a_batch_create_queues_the_rows_with_outcomes_sent_from_here(self):
        request = self._request()
        triggers_before = self._triggers()

        created = (
            self.env["maintenance.request.component"]
            .with_user(self.internal_user)
            .create(
                [
                    {"maintenance_request_id": request.id, "outcome": "REPAIRED", **_link_vals()},
                    {
                        "maintenance_request_id": request.id,
                        "outcome": "NO_ACTION",
                        **_link_vals("comp-spis", "Spis"),
                    },
                    {"maintenance_request_id": request.id, **_link_vals("comp-ugn", "Ugn")},
                    {
                        "maintenance_request_id": request.id,
                        "outcome": "REPLACED",
                        **_link_vals("comp-diskmaskin", "Diskmaskin"),
                    },
                ]
            )
        )

        self.assertEqual(
            [c.sync_state for c in created], ["pending", "pending", False, False]
        )
        self.assertEqual(self._triggers(), triggers_before + 1)

    def test_a_changed_outcome_is_queued_again_without_the_old_event(self):
        request = self._registered()
        self._sync()
        component = request.component_ids
        self.assertEqual(component.core_event_id, EVENT_ID)

        component.with_user(self.internal_user).write({"outcome": "NO_ACTION"})

        self.assertEqual(component.sync_state, "pending")
        self.assertFalse(component.core_event_id)
        self.assertFalse(component.sync_attempted_at)

    def test_a_changed_outcome_not_sent_from_here_clears_the_sync(self):
        request = self._registered()
        self._sync(_response(500, {"error": "Internal server error"}))
        component = request.component_ids
        self.assertEqual(component.sync_state, "failed")

        component.with_user(self.internal_user).write({"outcome": "REPLACED"})

        self.assertFalse(component.sync_state)
        self.assertFalse(component.sync_error)
        self.assertFalse(component.sync_attempted_at)

    def test_a_new_note_on_the_same_outcome_is_not_queued_again(self):
        request = self._registered(note="Bytt packning")
        self._sync()
        component = request.component_ids
        triggers_before = self._triggers()

        component.with_user(self.internal_user).write(
            {"outcome": "REPAIRED", "outcome_note": "Bytt packning och termostat"}
        )
        component.with_user(self.internal_user).write({"outcome_note": "Bytt allt"})

        self.assertEqual(component.sync_state, "synced")
        self.assertEqual(component.core_event_id, EVENT_ID)
        self.assertEqual(self._triggers(), triggers_before)

    def test_outcome_recorded_at_follows_the_outcome_and_its_note(self):
        request = self._request(_link_vals())
        component = request.component_ids.with_user(self.internal_user)

        component.write({"outcome": "REPAIRED"})
        self.assertTrue(component.outcome_recorded_at)

        component.sudo().write({"outcome_recorded_at": datetime(2000, 1, 1)})
        component.write({"outcome_note": "Bytt packning"})
        self.assertGreater(component.outcome_recorded_at, datetime(2000, 1, 1))

        component.write({"outcome": False})
        self.assertFalse(component.outcome_recorded_at)
        self.assertFalse(component.outcome_user_id)

    def test_a_client_cannot_set_the_server_set_fields(self):
        request = self._request(_link_vals())
        component = request.component_ids.with_user(self.internal_user)
        component.write({"outcome": "REPAIRED"})
        recorded_at = component.outcome_recorded_at

        component.write(
            {
                "sync_state": "synced",
                "sync_error": "Fel",
                "core_event_id": "made-up",
                "sync_attempted_at": "2026-01-01 00:00:00",
                "outcome_recorded_at": "2026-01-01 00:00:00",
            }
        )

        self.assertEqual(component.sync_state, "pending")
        self.assertFalse(component.sync_error)
        self.assertFalse(component.core_event_id)
        self.assertFalse(component.sync_attempted_at)
        self.assertEqual(component.outcome_recorded_at, recorded_at)

    def test_a_client_cannot_create_rows_with_the_server_set_fields(self):
        request = self._request()
        Component = (
            self.env["maintenance.request.component"]
            .with_user(self.internal_user)
            .with_context(default_sync_state="failed", default_sync_error="Fel")
        )

        with_outcome = Component.create(
            {
                "maintenance_request_id": request.id,
                "outcome": "REPAIRED",
                "sync_state": "synced",
                "core_event_id": "made-up",
                "sync_attempted_at": "2026-01-01 00:00:00",
                "outcome_recorded_at": "2020-01-01 00:00:00",
                **_link_vals(),
            }
        )
        without_outcome = Component.create(
            {"maintenance_request_id": request.id, **_link_vals("comp-spis", "Spis")}
        )

        self.assertEqual(with_outcome.sync_state, "pending")
        self.assertFalse(with_outcome.sync_error)
        self.assertFalse(with_outcome.core_event_id)
        self.assertFalse(with_outcome.sync_attempted_at)
        self.assertGreater(with_outcome.outcome_recorded_at, datetime(2020, 1, 2))
        self.assertFalse(without_outcome.sync_state)
        self.assertFalse(without_outcome.sync_error)


@tagged("onecore")
class TestComponentEventSync(ComponentEventCase):
    """The cron sends each queued row and stores core's answer."""

    def test_sends_the_event_core_expects(self):
        request = self._registered(note="Bytt termostat")
        request.write({"performed_date": datetime(2026, 11, 25, 23, 30)})
        component = request.component_ids

        self._sync()

        # One call per row: the event
        [call] = self.calls
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], f"{BASE_URL}/components/comp-frys/events")
        self.assertEqual(call["headers"], {"Authorization": "Bearer test-token"})
        self.assertEqual(call["timeout"], SEND_TIMEOUT)
        self.assertEqual(
            call["json"],
            {
                "eventType": "REPAIRED",
                # 23:30 UTC is already the next day in Stockholm
                "occurredAt": "2026-11-26",
                "sourceType": "WORK_ORDER",
                "sourceId": f"od-{request.id}",
                "actor": self.internal_user.login,
                "note": "Bytt termostat",
            },
        )
        self.assertEqual(component.sync_state, "synced")
        self.assertEqual(component.core_event_id, EVENT_ID)
        self.assertFalse(component.sync_error)
        self.assertTrue(component.sync_attempted_at)

    def test_occurred_at_is_the_stockholm_date_of_performed_date(self):
        for performed, expected in (
            (datetime(2026, 6, 30, 22, 30), "2026-07-01"),
            (datetime(2026, 6, 30, 21, 59), "2026-06-30"),
            (datetime(2026, 11, 25, 22, 59), "2026-11-25"),
        ):
            with self.subTest(performed=performed):
                request = self._registered()
                request.write({"performed_date": performed})
                self.calls.clear()

                self._sync()

                [call] = self._event_calls()
                self.assertEqual(call["json"]["occurredAt"], expected)

    def test_occurred_at_falls_back_to_when_the_outcome_was_recorded(self):
        request = self._request(_link_vals())
        component = request.component_ids
        component.with_user(self.internal_user).write({"outcome": "NO_ACTION"})
        component.write({"outcome_recorded_at": datetime(2026, 3, 1, 23, 15)})
        self.assertFalse(request.performed_date)

        self._sync()

        [call] = self._event_calls()
        self.assertEqual(call["json"]["occurredAt"], "2026-03-02")
        self.assertEqual(call["json"]["eventType"], "NO_ACTION")
        self.assertIsNone(call["json"]["note"])

    def test_remedied_is_sent_as_repaired(self):
        self._registered(_surface_vals(), outcome="REMEDIED")

        self._sync()

        [call] = self._event_calls()
        self.assertEqual(call["json"]["eventType"], "REPAIRED")

    def test_an_event_that_already_existed_is_synced_too(self):
        request = self._registered()
        other_id = "1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e5f"

        self._sync(_event(200, other_id))

        self.assertEqual(request.component_ids.sync_state, "synced")
        self.assertEqual(request.component_ids.core_event_id, other_id)

    def test_success_without_an_event_id_fails(self):
        for answer in (
            _response(201, {"content": {}}),
            _response(201, {"content": {"id": 123}}),
            _response(200, text="OK"),
            _response(204, text=""),
        ):
            with self.subTest(status=answer.status_code, body=answer.text):
                request = self._registered()

                self._sync(answer)

                component = request.component_ids
                self.assertEqual(component.sync_state, "failed")
                self.assertFalse(component.core_event_id)
                self.assertTrue(component.sync_error.startswith(f"od-{request.id}: "))

    def test_core_down_fails_and_a_later_run_syncs(self):
        for answer in (
            _response(500, {"error": "Internal server error"}),
            _response(502, text="Bad Gateway"),
            requests.Timeout("read timed out"),
            requests.ConnectionError("connection refused"),
        ):
            with self.subTest(answer=answer):
                request = self._registered()
                component = request.component_ids

                self._sync(answer)

                self.assertEqual(component.sync_state, "failed")
                self.assertFalse(component.core_event_id)
                self.assertTrue(component.sync_error.startswith(f"od-{request.id}: "))
                self.assertIn("skickas igen automatiskt", component.sync_error)
                self.assertTrue(component.sync_error.endswith(IF_IT_STAYS))

                self._later(component)
                self._sync(_event())

                self.assertEqual(component.sync_state, "synced")
                self.assertEqual(component.core_event_id, EVENT_ID)
                self.assertFalse(component.sync_error)

    def test_any_other_answer_fails_and_a_later_run_syncs(self):
        # Not core's own rejection: a proxy's 400, or a status core doesn't
        # reject an event with
        for answer in (
            _response(400, text="Bad Request"),
            _response(403, {"error": "Forbidden"}),
            _response(409, {"error": "Conflict"}),
        ):
            with self.subTest(status=answer.status_code):
                request = self._registered()
                component = request.component_ids

                self._sync(answer)

                self.assertEqual(component.sync_state, "failed")
                self.assertIn(f"(HTTP {answer.status_code})", component.sync_error)
                self.assertTrue(component.sync_error.endswith(IF_IT_STAYS))

                self._later(component)
                self._sync(_event())

                self.assertEqual(component.sync_state, "synced")

    def test_unauthorized_after_the_token_refresh_fails(self):
        request = self._registered()

        with mute_logger("odoo.addons.onecore_api.core_api"):
            self._sync(
                _response(401, text="Unauthorized"), _response(401, text="Unauthorized")
            )

        self.assertEqual(request.component_ids.sync_state, "failed")

    def test_a_token_that_cannot_be_fetched_fails_the_row_and_it_is_retried(self):
        # Core's token route answers 400 with JSON when a credential is
        # missing; that says nothing about the event
        request = self._registered()
        component = request.component_ids
        self.token_answers = [
            _response(400, {"errorMessage": "Missing parameter(s): username, password"})
        ]

        self._sync(_response(401, text="Unauthorized"))

        self.assertEqual(len(self._event_calls()), 1)
        self.assertEqual(len(self._token_calls()), 1)
        self.assertEqual(component.sync_state, "failed")
        self.assertIn("skickas igen automatiskt", component.sync_error)

        self._later(component)
        self._sync()

        self.assertEqual(component.sync_state, "synced")

    def test_a_failed_row_is_not_retried_by_the_next_run_at_once(self):
        request = self._registered()
        self._sync(requests.ConnectionError("connection refused"))
        self.calls.clear()

        self._sync()

        self.assertFalse(self._event_calls())
        self.assertEqual(request.component_ids.sync_state, "failed")

    def test_rejected_by_core_is_not_retried(self):
        zod_issues = [
            {"code": "too_small", "path": ["actor"], "message": "Required"},
            {"code": "invalid_string", "path": ["occurredAt"], "message": "Invalid date"},
        ]
        for answer, core_error in (
            (_response(400, {"error": zod_issues}), "actor: Required; occurredAt: Invalid date"),
            (_response(400, {"error": "Invalid UUID format"}), "Invalid UUID format"),
        ):
            with self.subTest(core_error=core_error):
                request = self._registered()
                component = request.component_ids

                self._sync(answer)

                self.assertEqual(component.sync_state, "rejected")
                self.assertTrue(component.sync_error.startswith(f"od-{request.id}: "))
                self.assertIn(core_error, component.sync_error)
                self.assertIn("Kontakta en administratör.", component.sync_error)

                self._later(component)
                self.calls.clear()
                self._sync()

                self.assertFalse(self._event_calls())
                self.assertEqual(component.sync_state, "rejected")

    def test_a_json_404_from_core_is_rejected_and_not_retried(self):
        # Core's own answer for a component it doesn't have
        request = self._registered()
        component = request.component_ids

        self._sync(_response(404, {"error": "Component not found"}))

        self.assertEqual(component.sync_state, "rejected")
        self.assertEqual(
            component.sync_error,
            f"od-{request.id}: OneCore tog inte emot utfallet för Frys (Kök): "
            "Component not found. Kontakta en administratör. När felet är rättat "
            "kan administratören skicka utfallet igen från ärendet.",
        )

        self._later(component)
        self.calls.clear()
        self._sync()

        self.assertFalse(self._event_calls())
        self.assertEqual(component.sync_state, "rejected")

    def test_a_404_without_json_is_a_core_without_the_route_and_is_retried(self):
        request = self._registered()
        component = request.component_ids

        self._sync(_response(404, text="Not Found"))

        self.assertEqual(component.sync_state, "failed")
        self.assertIn("(HTTP 404)", component.sync_error)
        self.assertIn("skickas igen automatiskt", component.sync_error)

        self._later(component)
        self._sync(_event())

        self.assertEqual(component.sync_state, "synced")
        self.assertEqual(component.core_event_id, EVENT_ID)

    def test_the_log_gives_cores_reason_for_a_rejection(self):
        for answer, logged in (
            (
                _response(400, {"error": "Invalid UUID format"}),
                "rejected (HTTP 400: Invalid UUID format)",
            ),
            (
                _response(404, {"error": "Component not found"}),
                "rejected (HTTP 404: Component not found)",
            ),
        ):
            with self.subTest(status=answer.status_code):
                request = self._registered()

                with self.assertLogs(SERVICE_LOGGER, level=logging.WARNING) as logs:
                    self._sync(answer)

                self.assertIn(
                    f"row {request.component_ids.id} (od-{request.id}) {logged}",
                    "\n".join(logs.output),
                )

    def test_a_row_without_an_actor_is_rejected_without_a_call(self):
        request = self._request(_link_vals())
        # As superuser: nobody is stamped as the outcome's author
        request.component_ids.write({"outcome": "REPAIRED"})

        self._sync()

        component = request.component_ids
        self.assertFalse(self._event_calls())
        self.assertEqual(component.sync_state, "rejected")
        self.assertTrue(component.sync_error.startswith(f"od-{request.id}: "))
        self.assertIn("saknar vem som registrerade", component.sync_error)

    def test_a_row_without_a_date_is_rejected_without_a_call(self):
        request = self._request(_link_vals())
        request.component_ids.write(
            {"outcome": "REPAIRED", "outcome_user_id": self.internal_user.id}
        )

        self._sync()

        component = request.component_ids
        self.assertFalse(self._event_calls())
        self.assertEqual(component.sync_state, "rejected")
        self.assertIn("saknar datum", component.sync_error)

    def test_a_row_on_an_archived_request_is_synced(self):
        request = self._registered()
        request.with_user(self.internal_user).write({"archive": True})

        self._sync()

        self.assertEqual(request.component_ids.sync_state, "synced")

    def test_a_change_committed_during_the_send_leaves_the_row_as_it_was_left(self):
        # Another transaction changed the row while the event was sent: the
        # cron's write of the result fails as a serialization failure
        request = self._registered(_link_vals(), _link_vals("comp-spis", "Spis"))
        fridge, stove = (
            request.component_ids.filtered(lambda c, name=name: c.component_name == name)
            for name in ("Frys", "Spis")
        )
        Component = type(fridge)
        write = Component.write

        def concurrent_write(records, vals):
            if "core_event_id" in vals and records == fridge:
                raise SerializationFailure(
                    "could not serialize access due to concurrent update"
                )
            return write(records, vals)

        with (
            patch.object(Component, "write", concurrent_write),
            self.assertLogs(SERVICE_LOGGER, level=logging.INFO) as logs,
        ):
            self._sync()

        self.assertEqual(len(self._event_calls()), 2)
        self.assertEqual(fridge.sync_state, "pending")
        self.assertFalse(fridge.core_event_id)
        self.assertFalse(fridge.sync_attempted_at)
        self.assertEqual(stove.sync_state, "synced")
        self.assertIn(
            f"row {fridge.id} (od-{request.id}) changed concurrently",
            "\n".join(logs.output),
        )

    def test_a_row_deleted_after_the_queue_was_read_is_skipped(self):
        request = self._registered(_link_vals(), _link_vals("comp-spis", "Spis"))
        fridge, stove = (
            request.component_ids.filtered(lambda c, name=name: c.component_name == name)
            for name in ("Frys", "Spis")
        )
        self.assertLess(fridge.id, stove.id)
        self._configure_core()
        deleted = []

        def commit_progress(*args, **kwargs):
            # The first commit comes after the queue is read
            if not deleted:
                fridge.unlink()
                deleted.append(True)
            return 1000.0

        with patch.object(
            type(self.env["ir.cron"]), "_commit_progress", side_effect=commit_progress
        ):
            self.env["maintenance.request.component"]._cron_sync_component_events()

        self.assertFalse(fridge.exists())
        [call] = self._event_calls()
        self.assertEqual(call["url"], f"{BASE_URL}/components/comp-spis/events")
        self.assertEqual(stove.sync_state, "synced")

    def test_pending_rows_go_first_then_the_least_recently_tried(self):
        request = self._registered(
            _link_vals(), _link_vals("comp-spis", "Spis"), _link_vals("comp-ugn", "Ugn")
        )
        fridge, stove, oven = (
            request.component_ids.filtered(lambda c, name=name: c.component_name == name)
            for name in ("Frys", "Spis", "Ugn")
        )
        now = fields.Datetime.now()
        fridge.write({"sync_state": "failed", "sync_attempted_at": now - timedelta(minutes=20)})
        stove.write({"sync_state": "failed", "sync_attempted_at": now - timedelta(minutes=40)})

        self._sync()

        self.assertEqual(
            [call["url"] for call in self._event_calls()],
            [
                f"{BASE_URL}/components/comp-ugn/events",
                f"{BASE_URL}/components/comp-spis/events",
                f"{BASE_URL}/components/comp-frys/events",
            ],
        )

    def test_the_time_budget_stops_the_run(self):
        request = self._registered(
            _link_vals(), _link_vals("comp-spis", "Spis"), _link_vals("comp-ugn", "Ugn")
        )

        commit = self._sync(time_left=[100.0, 100.0, ROW_BUDGET - 0.5])

        self.assertEqual(len(self._event_calls()), 2)
        self.assertEqual(
            sorted(request.component_ids.mapped("sync_state")),
            ["pending", "synced", "synced"],
        )
        self.assertEqual(commit.call_args_list[0].kwargs, {"remaining": 3})
        self.assertEqual([c.args for c in commit.call_args_list[1:]], [(1,), (1,)])

    def test_no_call_starts_without_time_for_it(self):
        request = self._registered()

        self._sync(time_left=[ROW_BUDGET - 0.5])

        self.assertFalse(self.calls)
        self.assertEqual(request.component_ids.sync_state, "pending")

    def test_a_row_starts_only_with_time_for_its_send_to_time_out(self):
        needed = sum(SEND_TIMEOUT)
        request = self._registered()

        self._sync(time_left=[needed - 0.5])

        self.assertFalse(self.calls)
        self.assertEqual(request.component_ids.sync_state, "pending")

        self._sync(time_left=[needed])

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(request.component_ids.sync_state, "synced")

    def test_rows_start_during_the_first_half_of_a_run(self):
        # A run starts work during MIN_TIME_PER_JOB; rows that could start
        # only in its first moments would drain a backlog a few rows per run
        request = self._registered()

        self._sync(time_left=[MIN_TIME_PER_JOB / 2])

        self.assertEqual(len(self._event_calls()), 1)
        self.assertEqual(request.component_ids.sync_state, "synced")

    def test_nothing_is_sent_while_onecore_is_not_configured(self):
        request = self._registered()

        self._sync(configure=False)

        self.assertFalse(self._event_calls())
        self.assertEqual(request.component_ids.sync_state, "pending")

    def test_the_log_names_the_row_but_not_the_actor_or_the_note(self):
        request = self._registered(note="Hemligt meddelande")
        component = request.component_ids

        with self.assertLogs(SERVICE_LOGGER, level=logging.INFO) as logs:
            self._sync()

        output = "\n".join(logs.output)
        self.assertIn(f"row {component.id} (od-{request.id}) synced (HTTP 201)", output)
        self.assertNotIn(self.internal_user.login, output)
        self.assertNotIn("Hemligt meddelande", output)


@tagged("onecore")
class TestResendComponentOutcomes(ComponentEventCase):
    """An administrator sends the outcomes OneCore didn't take again, once
    the reason is fixed."""

    def setUp(self):
        super().setUp()
        self.admin = create_internal_user(
            self.env,
            group_ids=[
                Command.set(
                    [
                        self.env.ref("base.group_user").id,
                        self.env.ref("maintenance.group_equipment_manager").id,
                        self.env.ref("base.group_system").id,
                    ]
                )
            ],
        )

    def _unsynced(self):
        """An ärende whose fridge failed, stove was rejected and oven synced."""
        request = self._registered(
            _link_vals(), _link_vals("comp-spis", "Spis"), _link_vals("comp-ugn", "Ugn")
        )
        self._sync(
            _response(500, {"error": "Internal server error"}),
            _response(400, {"error": "Invalid UUID format"}),
            _event(),
        )
        rows = {c.component_name: c for c in request.component_ids}
        self.assertEqual(rows["Frys"].sync_state, "failed")
        self.assertEqual(rows["Spis"].sync_state, "rejected")
        self.assertEqual(rows["Ugn"].sync_state, "synced")
        self.assertTrue(request.component_sync_pending)
        return request, rows

    def _resend(self, request, user=None):
        return request.with_user(user or self.admin).action_resend_component_outcomes()

    def test_an_administrator_queues_the_unsynced_rows_again(self):
        request, rows = self._unsynced()
        triggers_before = self._triggers()

        action = self._resend(request)

        # The form's button patch reloads the record on act_window_close, so
        # the badge goes without a manual reload
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(
            action["params"]["next"], {"type": "ir.actions.act_window_close"}
        )
        self.assertEqual(
            action["params"]["message"],
            f"od-{request.id}: Utfallen skickas till OneCore igen.",
        )

        for name in ("Frys", "Spis"):
            self.assertEqual(rows[name].sync_state, "pending")
            self.assertFalse(rows[name].sync_error)
            self.assertFalse(rows[name].sync_attempted_at)
        self.assertEqual(rows["Ugn"].sync_state, "synced")
        self.assertEqual(rows["Ugn"].core_event_id, EVENT_ID)
        self.assertEqual(self._triggers(), triggers_before + 1)
        self.assertFalse(request.component_sync_pending)

        self.calls.clear()
        self._sync()

        self.assertEqual(len(self._event_calls()), 2)
        self.assertEqual(
            [rows[name].sync_state for name in ("Frys", "Spis", "Ugn")],
            ["synced", "synced", "synced"],
        )

    def test_an_administrator_resends_on_an_archived_request_too(self):
        request, rows = self._unsynced()
        request.with_user(self.internal_user).write({"archive": True})

        self._resend(request)

        self.assertEqual(rows["Frys"].sync_state, "pending")
        self.assertEqual(rows["Spis"].sync_state, "pending")

    def test_rows_still_waiting_are_left_as_they_are_and_the_cron_runs(self):
        request = self._registered()
        component = request.component_ids
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE maintenance_request_component SET write_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(hours=1), component.id),
        )
        self.env.invalidate_all()
        written = component.write_date
        self.assertTrue(request.component_sync_pending)
        triggers_before = self._triggers()

        self._resend(request)

        self.assertEqual(component.sync_state, "pending")
        self.assertEqual(component.write_date, written)
        self.assertEqual(self._triggers(), triggers_before + 1)

    def test_only_an_administrator_may_resend(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        request, rows = self._unsynced()
        request.write({"maintenance_team_id": team.id})
        triggers_before = self._triggers()

        for user in (self.internal_user, contractor):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError) as refused:
                    self._resend(request, user=user)

                self.assertEqual(
                    refused.exception.args[0],
                    f"od-{request.id}: Bara en administratör kan skicka utfall till "
                    "OneCore igen. Kontakta en administratör.",
                )
        self.assertEqual(rows["Frys"].sync_state, "failed")
        self.assertEqual(rows["Spis"].sync_state, "rejected")
        self.assertEqual(self._triggers(), triggers_before)

    def test_resending_with_nothing_unsynced_is_refused(self):
        request = self._registered()
        self._sync()
        self.assertEqual(request.component_ids.sync_state, "synced")

        with self.assertRaises(UserError) as refused:
            self._resend(request)

        self.assertEqual(
            refused.exception.args[0],
            f"od-{request.id}: Alla utfall har kommit fram till OneCore eller "
            "väntar på att skickas. Ladda om sidan.",
        )

    def test_a_rejected_row_says_an_administrator_can_send_it_again(self):
        request, rows = self._unsynced()

        self.assertIn(
            "När felet är rättat kan administratören skicka utfallet igen från "
            "ärendet.",
            rows["Spis"].sync_error,
        )
        self.assertIn(rows["Spis"].sync_error, request.component_sync_message)

    def test_the_form_shows_the_button_to_administrators_under_the_badge(self):
        Request = self.env["maintenance.request"]
        for user, shown in ((self.admin, True), (self.internal_user, False)):
            with self.subTest(user=user.login):
                arch = etree.fromstring(
                    Request.with_user(user).get_view(view_type="form")["arch"]
                )

                buttons = arch.xpath(
                    "//button[@name='action_resend_component_outcomes']"
                )
                self.assertEqual(len(buttons), int(shown))
                if shown:
                    self.assertEqual(
                        buttons[0].getparent().get("invisible"),
                        "not component_sync_pending",
                    )
                    self.assertEqual(buttons[0].get("type"), "object")


@tagged("onecore")
class TestCreateComponentEventCall(ComponentEventCase):
    def test_posts_to_the_quoted_component_and_returns_any_status(self):
        self._configure_core()
        self.answers = [_response(404, {"error": "Component not found"})]

        response = core_api.CoreApi(self.env).create_component_event(
            "a/b c", {"eventType": "REPAIRED"}, timeout=7
        )

        self.assertEqual(response.status_code, 404)
        [call] = self._event_calls()
        self.assertEqual(call["url"], f"{BASE_URL}/components/a%2Fb%20c/events")
        self.assertEqual(call["json"], {"eventType": "REPAIRED"})
        self.assertEqual(call["timeout"], 7)
