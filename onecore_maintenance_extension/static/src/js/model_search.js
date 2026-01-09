/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onMounted } from "@odoo/owl";

/**
 * Model search widget with debounced autocomplete.
 * Searches OneCore component models as user types.
 *
 * Usage in XML:
 * <field name="form_model" widget="model_search"
 *        options="{'type_id_field': 'form_type_id', 'subtype_id_field': 'form_subtype_id'}"/>
 */
export class ModelSearch extends Component {
    static template = "onecore_maintenance_extension.ModelSearch";
    static props = {
        ...standardFieldProps,
        typeIdField: { type: String, optional: true },
        subtypeIdField: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            options: [],
            isOpen: false,
            searchText: "",
            highlightedIndex: -1,
            isLoading: false,
        });
        this.dropdownRef = useRef("dropdown");
        this.inputRef = useRef("input");
        this.debounceTimeout = null;

        onMounted(() => {
            document.addEventListener("click", this.onDocumentClick.bind(this));
        });
    }

    willUnmount() {
        document.removeEventListener("click", this.onDocumentClick.bind(this));
        if (this.debounceTimeout) {
            clearTimeout(this.debounceTimeout);
        }
    }

    get typeIdFieldName() {
        return this.props.typeIdField || "form_type_id";
    }

    get subtypeIdFieldName() {
        return this.props.subtypeIdField || "form_subtype_id";
    }

    get currentValue() {
        return this.props.record.data[this.props.name] || "";
    }

    get typeId() {
        return this.props.record.data[this.typeIdFieldName] || null;
    }

    get subtypeId() {
        return this.props.record.data[this.subtypeIdFieldName] || null;
    }

    get placeholder() {
        return this.props.placeholder || "Sök modell...";
    }

    onDocumentClick(ev) {
        if (this.dropdownRef.el && !this.dropdownRef.el.contains(ev.target)) {
            this.state.isOpen = false;
        }
    }

    onInputFocus() {
        // Only open dropdown if there's search text
        if (this.state.searchText.length >= 2) {
            this.state.isOpen = true;
        }
    }

    onInputChange(ev) {
        const value = ev.target.value;
        this.state.searchText = value;
        this.state.highlightedIndex = -1;

        // Clear any existing timeout
        if (this.debounceTimeout) {
            clearTimeout(this.debounceTimeout);
        }

        // Only search if at least 2 characters
        if (value.length < 2) {
            this.state.options = [];
            this.state.isOpen = false;
            return;
        }

        // Debounce the search by 300ms
        this.debounceTimeout = setTimeout(() => {
            this.searchModels(value);
        }, 300);
    }

    async searchModels(searchText) {
        this.state.isLoading = true;
        this.state.isOpen = true;

        try {
            const results = await this.orm.call(
                "maintenance.component.wizard",
                "search_component_models",
                [searchText, this.typeId, this.subtypeId]
            );

            this.state.options = results.map(item => ({
                modelName: item.modelName,
                manufacturer: item.manufacturer,
                label: item.label,
            }));
            this.state.highlightedIndex = this.state.options.length > 0 ? 0 : -1;
        } catch (e) {
            console.warn("ModelSearch: Failed to search models", e);
            this.state.options = [];
        } finally {
            this.state.isLoading = false;
        }
    }

    onInputKeydown(ev) {
        const options = this.state.options;

        switch (ev.key) {
            case "ArrowDown":
                ev.preventDefault();
                if (options.length > 0) {
                    this.state.highlightedIndex = Math.min(
                        this.state.highlightedIndex + 1,
                        options.length - 1
                    );
                }
                break;
            case "ArrowUp":
                ev.preventDefault();
                if (options.length > 0) {
                    this.state.highlightedIndex = Math.max(
                        this.state.highlightedIndex - 1,
                        0
                    );
                }
                break;
            case "Enter":
                ev.preventDefault();
                if (this.state.highlightedIndex >= 0 && options[this.state.highlightedIndex]) {
                    this.selectOption(options[this.state.highlightedIndex]);
                } else if (this.state.searchText) {
                    // Allow manual entry by pressing Enter
                    this.confirmManualEntry();
                }
                break;
            case "Escape":
                this.state.isOpen = false;
                break;
            case "Tab":
                // Allow tab to work normally, but confirm the current search text
                if (this.state.searchText && !this.state.isOpen) {
                    this.confirmManualEntry();
                }
                break;
        }
    }

    async selectOption(option) {
        this.state.isOpen = false;
        this.state.searchText = "";

        // Update the model field with the selected model name
        // This will trigger the _onchange_form_model handler
        await this.props.record.update({ [this.props.name]: option.modelName });
    }

    async confirmManualEntry() {
        this.state.isOpen = false;
        const value = this.state.searchText;
        this.state.searchText = "";

        // Update with the manually entered value
        await this.props.record.update({ [this.props.name]: value });
    }

    async onClearClick(ev) {
        ev.stopPropagation();
        this.state.searchText = "";
        this.state.options = [];
        this.state.isOpen = false;
        await this.props.record.update({ [this.props.name]: false });
    }

    onInputBlur() {
        // Small delay to allow click events on dropdown items to fire first
        setTimeout(() => {
            if (this.state.searchText && !this.state.isOpen) {
                this.confirmManualEntry();
            }
        }, 200);
    }
}

ModelSearch.template = "onecore_maintenance_extension.ModelSearch";

// Register the field widget
registry.category("fields").add("model_search", {
    component: ModelSearch,
    supportedTypes: ["char"],
    extractProps: ({ attrs, options }) => ({
        typeIdField: options.type_id_field || attrs.type_id_field,
        subtypeIdField: options.subtype_id_field || attrs.subtype_id_field,
        placeholder: attrs.placeholder,
    }),
});
