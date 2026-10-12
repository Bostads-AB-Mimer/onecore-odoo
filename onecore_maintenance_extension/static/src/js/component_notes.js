/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

import { linkFields } from "./component_link_fields";

/**
 * "Komponent (Rum): note" for every selected component, under the ärende's
 * description, so whoever opens the ärende sees them first. Read-only: the
 * components and their notes are edited in the room grid ("Rum och
 * komponenter").
 */
export class ComponentNotes extends Component {
    static template = "onecore_maintenance_extension.ComponentNotes";
    static props = { ...standardFieldProps };

    get links() {
        // Same order as the grid: room, then component
        return [...this.props.record.data[this.props.name].records].sort(
            (a, b) =>
                a.data.room_sequence - b.data.room_sequence ||
                a.data.label.localeCompare(b.data.label, "sv")
        );
    }
}

registry.category("fields").add("component_notes", {
    component: ComponentNotes,
    supportedTypes: ["one2many"],
    relatedFields: linkFields,
});
