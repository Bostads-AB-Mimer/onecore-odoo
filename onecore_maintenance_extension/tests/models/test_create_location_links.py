"""Creating an ärende found by a building or property search.

The form's onchange copies the search option's id into building_id and
property_id. That id is not a building or property, so the request is only
created if those links are left out and built from the options instead.
"""
from unittest.mock import patch

from odoo import api
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import (
    create_building_option,
    create_internal_user,
    create_maintenance_request,
    create_property_option,
    create_staircase_option,
)


@tagged("onecore")
class TestCreateLocationLinks(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user = create_internal_user(self.env)
        self.user_env = self.env(user=self.user)

    def _unused_id(self, model):
        """An id no record of ``model`` has, like a search option's id in prod."""
        last = self.env[model].sudo().search([], order="id desc", limit=1)
        return last.id + 1000

    def test_create_ignores_a_building_link_sent_with_its_option(self):
        option = create_building_option(self.user_env)

        request = create_maintenance_request(
            self.user_env,
            space_caption="Byggnad",
            building_option_id=option.id,
            building_id=self._unused_id("maintenance.building"),
        )

        self.assertEqual(request.building_id.code, option.code)
        self.assertEqual(request.building_id.maintenance_request_id, request)

    def test_create_ignores_a_property_link_sent_with_its_option(self):
        option = create_property_option(self.user_env)

        request = create_maintenance_request(
            self.user_env,
            space_caption="Fastighet",
            property_option_id=option.id,
            property_id=self._unused_id("maintenance.property"),
        )

        self.assertEqual(request.property_id.code, option.code)
        self.assertEqual(request.property_id.maintenance_request_id, request)

    def test_create_ignores_a_staircase_link_sent_with_its_option(self):
        option = create_staircase_option(self.user_env)

        request = create_maintenance_request(
            self.user_env,
            space_caption="Uppgång",
            staircase_option_id=option.id,
            staircase_id=self._unused_id("maintenance.staircase"),
        )

        self.assertEqual(request.staircase_id.code, option.code)
        self.assertEqual(request.staircase_id.maintenance_request_id, request)

    def test_batch_create_ignores_each_link_sent_with_its_option(self):
        building = create_building_option(self.user_env)
        prop = create_property_option(self.user_env)
        category = self.env.ref("onecore_maintenance_extension.category_1")
        common = {"maintenance_request_category_id": category.id, "priority_expanded": "7"}

        requests = self.user_env["maintenance.request"].create(
            [
                {
                    **common,
                    "name": "Byggnad",
                    "space_caption": "Byggnad",
                    "building_option_id": building.id,
                    "building_id": self._unused_id("maintenance.building"),
                },
                {
                    **common,
                    "name": "Fastighet",
                    "space_caption": "Fastighet",
                    "property_option_id": prop.id,
                    "property_id": self._unused_id("maintenance.property"),
                },
            ]
        )

        self.assertEqual(requests[0].building_id.code, building.code)
        self.assertEqual(requests[1].property_id.code, prop.code)

    def test_form_does_not_send_the_location_links(self):
        """Saving a new ärende through the form, as the browser does, sends
        neither link the onchange filled with an option id."""
        Request = self.user_env["maintenance.request"]
        original_create = type(Request).create
        sent = []

        @api.model_create_multi
        def spy_create(model, vals_list):
            sent.extend(vals_list)
            return original_create(model, vals_list)

        cases = (
            ("Byggnad", "building_option_id", create_building_option(self.user_env)),
            ("Fastighet", "property_option_id", create_property_option(self.user_env)),
        )
        for space_caption, option_field, option in cases:
            with self.subTest(space_caption=space_caption):
                sent.clear()
                form = Form(Request)
                form.name = f"Test {space_caption}"
                form.maintenance_request_category_id = self.env.ref(
                    "onecore_maintenance_extension.category_1"
                )
                form.space_caption = space_caption
                form[option_field] = option

                with patch.object(type(Request), "create", spy_create):
                    request = form.save()

                self.assertTrue(sent)
                for vals in sent:
                    self.assertNotIn("building_id", vals)
                    self.assertNotIn("property_id", vals)
                link = request.building_id or request.property_id
                self.assertEqual(link.code, option.code)
