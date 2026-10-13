/** @odoo-module **/

// Fields of maintenance.request.component that the room grid and the notes
// under the description read and write.
const LINK_FIELDS = [
    ["onecore_component_id", "char"],
    ["installation_id", "char"],
    ["room_id", "char"],
    ["room_name", "char"],
    ["room_sequence", "integer"],
    ["label", "char"],
    ["subtype_name", "char"],
    ["category_type", "char"],
    ["note", "text"],
];

/**
 * relatedFields for a widget on maintenance.request.component_link_ids.
 *
 * readonly: false is required. Odoo makes relatedFields readonly by default
 * and leaves readonly fields out of the save, so a new link would be sent
 * without its values and note edits would be dropped.
 */
export function linkFields() {
    return LINK_FIELDS.map(([name, type]) => ({ name, type, readonly: false }));
}
