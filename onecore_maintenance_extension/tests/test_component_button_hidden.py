from lxml import etree

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("onecore")
class TestComponentButtonHidden(TransactionCase):
    def test_component_wizard_button_is_hidden_in_the_request_form(self):
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_form_extension"
        )
        buttons = etree.fromstring(view.arch_db).xpath(
            '//button[@name="open_component_wizard"]'
        )
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get("invisible"), "1")
