/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState } from "@odoo/owl";

/**
 * Paste-to-populate widget (MIM-1841): a text input + "Hämta" button.
 * On click/Enter it commits the typed value to the bound char field, which
 * fires that field's @api.onchange to fetch and fill the form (no save).
 *
 * Usage:
 *   <field name="rental_object_lookup" widget="lookup_button"
 *          placeholder="Klistra in objektnummer" nolabel="1"/>
 */
export class LookupButtonField extends Component {
    static template = "onecore_maintenance_extension.LookupButtonField";
    static props = {
        ...standardFieldProps,
        buttonLabel: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ value: "" });
    }

    get placeholder() {
        return this.props.placeholder || "";
    }

    get buttonLabel() {
        return this.props.buttonLabel || "Hämta";
    }

    onInput(ev) {
        this.state.value = ev.target.value;
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.fetch();
        }
    }

    async fetch() {
        const value = (this.state.value || "").trim();
        if (!value) {
            return;
        }
        await this.props.record.update({ [this.props.name]: value });
        this.state.value = "";
    }
}

registry.category("fields").add("lookup_button", {
    component: LookupButtonField,
    supportedTypes: ["char"],
    extractProps: ({ attrs, options }) => ({
        buttonLabel: attrs.button_label || options.button_label,
        placeholder: attrs.placeholder,
    }),
});
