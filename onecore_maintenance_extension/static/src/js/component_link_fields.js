/** @odoo-module **/

// Fields of maintenance.request.component that the room grid and the notes
// under the description read and write.
const LINK_FIELDS = [
    ["onecore_component_id", "char"],
    ["installation_id", "char"],
    ["rental_id", "char"],
    ["space_id", "char"],
    ["space_name", "char"],
    ["space_sequence", "integer"],
    ["component_name", "char"],
    ["subtype_name", "char"],
    ["subtype_xpand_code", "char"],
    ["category_type", "char"],
    ["note", "text"],
];

/**
 * relatedFields for a widget on maintenance.request.component_ids.
 *
 * readonly: false is required. Odoo makes relatedFields readonly by default
 * and leaves readonly fields out of the save, so a new link would be sent
 * without its values and note edits would be dropped.
 */
export function linkFields() {
    return LINK_FIELDS.map(([name, type]) => ({ name, type, readonly: false }));
}
