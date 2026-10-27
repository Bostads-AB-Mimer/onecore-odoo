/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";
import { isMissingRequiredAnswer } from "./required_answers";

/**
 * Block saving while a required question is unanswered, through the same
 * path Odoo uses for required fields ("Missing required fields" notice and
 * the field marked invalid). Odoo's own check skips property sub-fields.
 */
patch(Record.prototype, {
    _checkValidity(options = {}) {
        const valid = super._checkValidity(options);
        const missing = this._propertiesFieldsWithMissingAnswers();
        if (!missing.length) {
            return valid;
        }
        if (options.silent) {
            return false;
        }
        for (const fieldName of missing) {
            this._unsetRequiredFields.add(fieldName);
            this._invalidFields.add(fieldName);
        }
        if (valid && options.displayNotification) {
            this._closeInvalidFieldsNotification = this._displayInvalidFieldNotification();
        }
        return false;
    },

    _propertiesFieldsWithMissingAnswers() {
        const missing = [];
        for (const fieldName in this.activeFields) {
            if (this.fields[fieldName]?.type !== "properties" || this._isInvisible(fieldName)) {
                continue;
            }
            const properties = this.data[fieldName] || [];
            if (properties.some(isMissingRequiredAnswer)) {
                missing.push(fieldName);
            }
        }
        return missing;
    },
});
