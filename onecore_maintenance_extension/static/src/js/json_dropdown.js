/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, useRef, onMounted, onWillUpdateProps } from "@odoo/owl";

/**
 * Dynamic dropdown widget that populates options from a JSON field.
 *
 * Usage in XML:
 * <field name="form_category" widget="json_dropdown"
 *        options="{'json_field': 'available_categories_json', 'label_field': 'categoryName', 'value_field': 'id', 'id_field': 'form_category_id'}"/>
 */
export class JsonDropdown extends Component {
    static template = "onecore_maintenance_extension.JsonDropdown";
    static props = {
        ...standardFieldProps,
        jsonField: { type: String, optional: true },
        labelField: { type: String, optional: true },
        valueField: { type: String, optional: true },
        idField: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        autoOpen: { type: Boolean, optional: true },
    };

    setup() {
        this.state = useState({
            options: [],
            isOpen: false,
            searchText: "",
            highlightedIndex: -1,
        });
        this.dropdownRef = useRef("dropdown");
        this.inputRef = useRef("input");

        onMounted(() => {
            this.loadOptions();
            document.addEventListener("click", this.onDocumentClick.bind(this));
        });

        onWillUpdateProps((nextProps) => {
            // Reload options when the JSON field changes
            this.loadOptionsFromProps(nextProps);
        });
    }

    willUnmount() {
        document.removeEventListener("click", this.onDocumentClick.bind(this));
    }

    get jsonFieldName() {
        return this.props.jsonField || "available_options_json";
    }

    get labelFieldName() {
        return this.props.labelField || "name";
    }

    get valueFieldName() {
        return this.props.valueField || "id";
    }

    get idFieldName() {
        return this.props.idField || null;
    }

    get currentValue() {
        return this.props.record.data[this.props.name] || "";
    }

    get currentId() {
        if (this.idFieldName) {
            return this.props.record.data[this.idFieldName] || "";
        }
        return "";
    }

    get filteredOptions() {
        const search = this.state.searchText.toLowerCase();
        if (!search) return this.state.options;
        return this.state.options.filter(opt =>
            opt.label.toLowerCase().includes(search)
        );
    }

    get placeholder() {
        return this.props.placeholder || "Välj...";
    }

    loadOptions() {
        this.loadOptionsFromProps(this.props);
    }

    loadOptionsFromProps(props) {
        const jsonData = props.record.data[this.jsonFieldName];
        if (!jsonData) {
            this.state.options = [];
            return;
        }

        try {
            const parsed = JSON.parse(jsonData);
            if (Array.isArray(parsed)) {
                this.state.options = parsed.map(item => ({
                    label: item[this.labelFieldName] || "",
                    value: item[this.valueFieldName] || "",
                    raw: item,
                }));
            } else {
                this.state.options = [];
            }
        } catch (e) {
            console.warn("JsonDropdown: Failed to parse JSON", e);
            this.state.options = [];
        }
    }

    onDocumentClick(ev) {
        if (this.dropdownRef.el && !this.dropdownRef.el.contains(ev.target)) {
            this.state.isOpen = false;
        }
    }

    onInputFocus() {
        // Only auto-open if autoOpen is not explicitly set to false
        if (this.props.autoOpen !== false) {
            this.state.isOpen = true;
        }
        this.state.searchText = "";
        this.loadOptions(); // Reload in case JSON changed
    }

    onInputChange(ev) {
        this.state.searchText = ev.target.value;
        this.state.isOpen = true;
        this.state.highlightedIndex = 0;
    }

    onInputKeydown(ev) {
        const options = this.filteredOptions;

        switch (ev.key) {
            case "ArrowDown":
                ev.preventDefault();
                this.state.highlightedIndex = Math.min(
                    this.state.highlightedIndex + 1,
                    options.length - 1
                );
                break;
            case "ArrowUp":
                ev.preventDefault();
                this.state.highlightedIndex = Math.max(
                    this.state.highlightedIndex - 1,
                    0
                );
                break;
            case "Enter":
                ev.preventDefault();
                if (this.state.highlightedIndex >= 0 && options[this.state.highlightedIndex]) {
                    this.selectOption(options[this.state.highlightedIndex]);
                }
                break;
            case "Escape":
                this.state.isOpen = false;
                break;
        }
    }

    async selectOption(option) {
        this.state.isOpen = false;
        this.state.searchText = "";

        // Update both the display field and the ID field
        const updates = { [this.props.name]: option.label };
        if (this.idFieldName) {
            updates[this.idFieldName] = option.value;
        }

        await this.props.record.update(updates);
    }

    async onClearClick(ev) {
        ev.stopPropagation();
        const updates = { [this.props.name]: false };
        if (this.idFieldName) {
            updates[this.idFieldName] = false;
        }
        await this.props.record.update(updates);
    }

    toggleDropdown() {
        this.state.isOpen = !this.state.isOpen;
        if (this.state.isOpen) {
            this.loadOptions();
        }
    }
}

JsonDropdown.template = "onecore_maintenance_extension.JsonDropdown";

// Register the field widget
registry.category("fields").add("json_dropdown", {
    component: JsonDropdown,
    supportedTypes: ["char", "text"],
    extractProps: ({ attrs, options }) => ({
        jsonField: options.json_field || attrs.json_field,
        labelField: options.label_field || attrs.label_field,
        valueField: options.value_field || attrs.value_field,
        idField: options.id_field || attrs.id_field,
        placeholder: attrs.placeholder,
        autoOpen: options.autoOpen !== undefined ? options.autoOpen : true,
    }),
});
