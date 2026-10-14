/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { x2ManyCommands } from "@web/core/orm_service";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { TextField } from "@web/views/fields/text/text_field";
import { Component, useState, useEffect, useRef, onPatched } from "@odoo/owl";

import { linkFields } from "./component_link_fields";

/**
 * "Rum och komponenter": one column per room of the rental object, listing
 * the components installed there. Checking a component adds a line to
 * component_ids and opens its note right under it; the change is saved
 * with the form like any other field.
 *
 * Rooms and components come from OneCore through get_room_components, loaded
 * after the form has rendered so a slow OneCore never delays the ärende.
 */
export class RoomComponents extends Component {
    static template = "onecore_maintenance_extension.RoomComponents";
    // TextField directly, not the Field wrapper: lines of a one2many are in
    // readonly mode, and the wrapper would always render them as plain text.
    // TextField's input hook still commits the note on save.
    static components = { TextField };
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.rootRef = useRef("root");
        // Component whose note should get focus once it has rendered
        this.focusNoteOf = null;
        onPatched(() => {
            if (this.focusNoteOf) {
                const selector = `[data-component-id="${CSS.escape(this.focusNoteOf)}"] textarea`;
                const textarea = this.rootRef.el?.querySelector(selector);
                if (textarea) {
                    textarea.focus();
                    this.focusNoteOf = null;
                }
            }
        });
        this.state = useState({
            // Loading from the first render: before the result arrives,
            // saved components would otherwise show as removed
            loading: Boolean(this.rentalId),
            ok: true,
            rooms: [],
            // Rental id fully loaded for. Only set on success, so a failed or
            // partial load is retried, like the server, which doesn't cache it
            loadedFor: null,
        });
        // Latest request; answers to older ones are ignored
        this.requestCount = 0;
        // Component ids with an add or remove in flight: the list update is
        // async, and a double click must not add the same component twice.
        this.pending = new Set();

        useEffect(
            (rentalId) => {
                if (!rentalId) {
                    this.requestCount++;
                    Object.assign(this.state, {
                        loading: false,
                        ok: true,
                        rooms: [],
                        loadedFor: null,
                    });
                    return;
                }
                if (this.state.loadedFor === rentalId) {
                    return;
                }
                const request = ++this.requestCount;
                this.state.loading = true;
                this.orm
                    .call("maintenance.request", "get_room_components", [rentalId])
                    .then((result) => {
                        if (request === this.requestCount) {
                            this.state.ok = result.ok;
                            this.state.rooms = result.rooms;
                            const complete =
                                result.ok && result.rooms.every((room) => room.loaded);
                            this.state.loadedFor = complete ? rentalId : null;
                        }
                    })
                    .catch((e) => {
                        console.warn("Failed to load rooms and components", e);
                        if (request === this.requestCount) {
                            this.state.ok = false;
                            this.state.rooms = [];
                            this.state.loadedFor = null;
                        }
                    })
                    .finally(() => {
                        if (request === this.requestCount) {
                            this.state.loading = false;
                        }
                    });
            },
            // The ärende too: the form keeps this widget when paging, and
            // another ärende on the same apartment retries a failed load
            () => [this.props.record.data.component_rental_id, this.props.record.resId]
        );
    }

    get list() {
        return this.props.record.data[this.props.name];
    }

    get rentalId() {
        return this.props.record.data.component_rental_id;
    }

    /**
     * The rooms OneCore returned, plus selected components it didn't return,
     * shown from the snapshot on the link: uninstalled since, in a room that
     * failed to load, or everything when OneCore is unreachable.
     */
    get columns() {
        const linksById = new Map(
            this.list.records.map((link) => [link.data.onecore_component_id, link])
        );
        const shownIds = new Set();
        const columns = this.state.rooms.map((room) => ({
            key: room.id,
            name: room.name,
            sequence: room.sequence,
            loaded: room.loaded,
            items: room.components.map((component) => {
                shownIds.add(component.id);
                return {
                    key: component.id,
                    label: component.number
                        ? `${component.label} ${component.number}`
                        : component.label,
                    subtypeName: component.subtype_name || "",
                    link: linksById.get(component.id),
                    room,
                    component,
                    removed: false,
                };
            }),
        }));

        const columnsByRoomId = new Map(columns.map((column) => [column.key, column]));
        for (const link of this.list.records) {
            const componentId = link.data.onecore_component_id;
            if (shownIds.has(componentId)) {
                continue;
            }
            const roomId = link.data.space_id || `snapshot:${link.data.space_name}`;
            let column = columnsByRoomId.get(roomId);
            if (!column) {
                // The room itself is gone from OneCore, or nothing could be
                // fetched at all
                column = {
                    key: roomId,
                    name: link.data.space_name || "Okänt rum",
                    sequence: link.data.space_sequence,
                    loaded: this.state.ok,
                    items: [],
                };
                columnsByRoomId.set(roomId, column);
                columns.push(column);
            }
            column.items.push({
                key: componentId,
                label: link.data.component_name,
                subtypeName: link.data.subtype_name || "",
                link,
                // Only known to be removed when OneCore answered for the room
                removed: this.state.ok && column.loaded,
            });
        }

        for (const column of columns) {
            column.selectedCount = column.items.filter((item) => item.link).length;
        }
        return columns.sort(
            (a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name, "sv")
        );
    }

    async toggle(item) {
        if (this.props.readonly || this.pending.has(item.key)) {
            return;
        }
        this.pending.add(item.key);
        try {
            const link = this.list.records.find(
                (record) => record.data.onecore_component_id === item.key
            );
            if (link) {
                await this.list.delete(link);
            } else if (item.component) {
                const { room, component } = item;
                // Set before the update: the note may render before it resolves
                this.focusNoteOf = component.id;
                await this.list.applyCommands([
                    [
                        x2ManyCommands.CREATE,
                        false,
                        {
                            onecore_component_id: component.id,
                            installation_id: component.installation_id || false,
                            rental_id: this.rentalId,
                            space_id: room.id,
                            space_name: room.name,
                            space_sequence: room.sequence,
                            // Without the grid's number: it shifts over time
                            component_name: component.label,
                            subtype_name: component.subtype_name || false,
                            subtype_xpand_code: component.subtype_xpand_code || false,
                            category_type: component.category_type || false,
                            note: false,
                        },
                    ],
                ]);
            }
        } catch (error) {
            this.focusNoteOf = null;
            throw error;
        } finally {
            this.pending.delete(item.key);
        }
    }
}

registry.category("fields").add("room_components", {
    component: RoomComponents,
    supportedTypes: ["one2many"],
    relatedFields: linkFields,
    fieldDependencies: [{ name: "component_rental_id", type: "char" }],
});

/**
 * "N komponenter valda" in the section header. Counts the unsaved selection
 * too: it reads the same lines as the grid.
 */
export class RoomComponentsCount extends Component {
    static template = "onecore_maintenance_extension.RoomComponentsCount";
    static props = { ...standardWidgetProps };

    get count() {
        return this.props.record.data.component_ids?.count || 0;
    }
}

registry.category("view_widgets").add("room_components_count", {
    component: RoomComponentsCount,
    additionalClasses: ["float-end"],
});
