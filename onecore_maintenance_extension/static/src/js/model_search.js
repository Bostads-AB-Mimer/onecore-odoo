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

    /**
     * Cleanup: removes document click listener and clears debounce timeout.
     */
    willUnmount() {
        document.removeEventListener("click", this.onDocumentClick.bind(this));
        if (this.debounceTimeout) {
            clearTimeout(this.debounceTimeout);
        }
    }

    /**
     * Returns the field name for the component type ID filter.
     * @returns {string} Type ID field name
     */
    get typeIdFieldName() {
        return this.props.typeIdField || "form_type_id";
    }

    /**
     * Returns the field name for the component subtype ID filter.
     * @returns {string} Subtype ID field name
     */
    get subtypeIdFieldName() {
        return this.props.subtypeIdField || "form_subtype_id";
    }

    /**
     * Returns the current model name value.
     * @returns {string} Current value
     */
    get currentValue() {
        return this.props.record.data[this.props.name] || "";
    }

    /**
     * Returns the current type ID for filtering search results.
     * @returns {string|null} Type ID or null
     */
    get typeId() {
        return this.props.record.data[this.typeIdFieldName] || null;
    }

    /**
     * Returns the current subtype ID for filtering search results.
     * @returns {string|null} Subtype ID or null
     */
    get subtypeId() {
        return this.props.record.data[this.subtypeIdFieldName] || null;
    }

    /**
     * Returns the placeholder text for the search input.
     * @returns {string} Placeholder text
     */
    get placeholder() {
        return this.props.placeholder || "Sök modell...";
    }

    /**
     * Closes dropdown when clicking outside the component.
     * @param {MouseEvent} ev - The click event
     */
    onDocumentClick(ev) {
        if (this.dropdownRef.el && !this.dropdownRef.el.contains(ev.target)) {
            this.state.isOpen = false;
        }
    }

    /**
     * Handles input focus event. Opens dropdown if search text exists.
     */
    onInputFocus() {
        if (this.state.searchText.length >= 2) {
            this.state.isOpen = true;
        }
    }

    /**
     * Handles input text changes with debounced API search.
     * @param {Event} ev - The input event
     */
    onInputChange(ev) {
        const value = ev.target.value;
        this.state.searchText = value;
        this.state.highlightedIndex = -1;

        if (this.debounceTimeout) {
            clearTimeout(this.debounceTimeout);
        }

        if (value.length < 2) {
            this.state.options = [];
            this.state.isOpen = false;
            return;
        }

        this.debounceTimeout = setTimeout(() => {
            this.searchModels(value);
        }, 300);
    }

    /**
     * Searches for component models via the OneCore API.
     * @param {string} searchText - The search query
     */
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

    /**
     * Handles keyboard navigation (Arrow keys, Enter, Escape, Tab).
     * @param {KeyboardEvent} ev - The keydown event
     */
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
                    this.confirmManualEntry();
                }
                break;
            case "Escape":
                this.state.isOpen = false;
                break;
            case "Tab":
                if (this.state.searchText && !this.state.isOpen) {
                    this.confirmManualEntry();
                }
                break;
        }
    }

    /**
     * Selects an option and updates the record with the model name.
     * Triggers the _onchange_form_model handler in the backend.
     * @param {Object} option - The selected option object
     */
    async selectOption(option) {
        this.state.isOpen = false;
        this.state.searchText = "";
        await this.props.record.update({ [this.props.name]: option.modelName });
    }

    /**
     * Confirms manual entry of a model name not in the autocomplete list.
     */
    async confirmManualEntry() {
        this.state.isOpen = false;
        const value = this.state.searchText;
        this.state.searchText = "";
        await this.props.record.update({ [this.props.name]: value });
    }

    /**
     * Clears the search input and selected value.
     * @param {MouseEvent} ev - The click event
     */
    async onClearClick(ev) {
        ev.stopPropagation();
        this.state.searchText = "";
        this.state.options = [];
        this.state.isOpen = false;
        await this.props.record.update({ [this.props.name]: false });
    }

    /**
     * Handles input blur event. Confirms manual entry after a short delay.
     */
    onInputBlur() {
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
