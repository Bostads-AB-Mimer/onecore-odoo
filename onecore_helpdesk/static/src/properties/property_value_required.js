/** @odoo-module **/

import { PropertyValue } from "@web/views/fields/properties/property_value";

// Let the properties field pass the definition's `required` flag down to the
// value widget (used by property_value_required.xml).
PropertyValue.props = {
    ...PropertyValue.props,
    required: { type: Boolean, optional: true },
};
