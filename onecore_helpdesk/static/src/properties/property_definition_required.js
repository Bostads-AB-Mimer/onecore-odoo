/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PropertyDefinition } from "@web/views/fields/properties/property_definition";

/**
 * Required answers for helpdesk forms: the question editor gets an
 * "Obligatorisk" checkbox that writes the `required` key on the definition.
 * The key is allowed server side by onecore_helpdesk/models/base.py.
 */
patch(PropertyDefinition.prototype, {
    onRequiredChange(checked) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            required: !!checked,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    },
});
