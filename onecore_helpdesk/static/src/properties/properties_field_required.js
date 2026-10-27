/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PropertiesField } from "@web/views/fields/properties/properties_field";
import { isMissingRequiredAnswer } from "./required_answers";

patch(PropertiesField.prototype, {
    /**
     * Highlight an unanswered required question, but only once the record has
     * been flagged invalid (i.e. the user tried to save), like other fields.
     *
     * @param {Object} property
     * @returns {boolean}
     */
    isMissingRequiredAnswer(property) {
        return (
            this.props.record.isFieldInvalid?.(this.props.name) &&
            isMissingRequiredAnswer(property)
        );
    },
});
