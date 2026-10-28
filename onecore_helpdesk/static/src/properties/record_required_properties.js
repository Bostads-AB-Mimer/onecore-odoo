/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";
import { isMissingRequiredAnswer } from "./required_answers";

/**
 * Block saving while a required question is unanswered, through the same
 * path Odoo uses for required fields ("Missing required fields" notice and
 * the field marked invalid). Odoo's own check skips property sub-fields.
 *
 * Mirrors the server: answers are checked on a new record and when the
 * answers or the form (the definition record) changed, never on an untouched
 * old ticket, so a stage move on a ticket that arrived without answers
 * still saves.
 *
 * Odoo also runs this check after every field edit with `removeInvalidOnly`,
 * to clear marks on fields that became valid. In that mode a block only
 * stays marked if it already was; new marks appear on a save attempt, like
 * for other required fields.
 */
patch(Record.prototype, {
    _checkValidity(options = {}) {
        const missing = this._propertiesFieldsWithMissingAnswers();
        const markedBefore = missing.filter((fieldName) => this._invalidFields.has(fieldName));
        // the notification is shown once, with the questions included
        const valid = super._checkValidity({ ...options, displayNotification: false });
        if (options.silent) {
            return valid && !missing.length;
        }
        const toMark = options.removeInvalidOnly ? markedBefore : missing;
        for (const fieldName of toMark) {
            this._unsetRequiredFields.add(fieldName);
            this._invalidFields.add(fieldName);
        }
        const isValid = !this._invalidFields.size;
        if (!isValid && options.displayNotification) {
            this._closeInvalidFieldsNotification = this._displayInvalidFieldNotification();
        }
        return isValid;
    },

    _propertiesFieldsWithMissingAnswers() {
        const missing = [];
        for (const fieldName in this.activeFields) {
            const field = this.fields[fieldName];
            if (field?.type !== "properties" || this._isInvisible(fieldName)) {
                continue;
            }
            const touched =
                this.isNew ||
                fieldName in this._changes ||
                field.definition_record in this._changes;
            if (!touched) {
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
