/** @odoo-module **/

/**
 * Mirror of HelpdeskTicket._is_missing_required_answer in Python: a property
 * flagged `required` without an answer. Separators and booleans never count,
 * and 0 is an answer. Relational answers (many2one, many2many, tags) are
 * arrays in the client's read format.
 *
 * @param {Object} property definition with value, in the client's read format
 * @returns {boolean}
 */
export function isMissingRequiredAnswer(property) {
    if (
        !property ||
        !property.required ||
        property.definition_deleted ||
        ["separator", "boolean"].includes(property.type)
    ) {
        return false;
    }
    const value = property.value;
    if (value === undefined || value === null || value === false || value === "") {
        return true;
    }
    return Array.isArray(value) && value.length === 0;
}
