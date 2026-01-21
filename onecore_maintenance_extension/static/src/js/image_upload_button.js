/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, useRef } from "@odoo/owl";

/**
 * Custom circular image upload button component.
 * Shows a styled button when no image, shows preview when image uploaded.
 */
export class ImageUploadButton extends Component {
    static template = "onecore_maintenance_extension.ImageUploadButton";
    static props = {
        ...standardFieldProps,
        secondary: { type: Boolean, optional: true },
    };

    setup() {
        this.fileInputRef = useRef("fileInput");
        this.state = useState({
            previewUrl: null,
        });
        this.updatePreview();
    }

    /**
     * Checks if an image has been uploaded.
     * @returns {boolean} True if image data exists
     */
    get hasImage() {
        return Boolean(this.props.record.data[this.props.name]);
    }

    /**
     * Constructs a data URL from the base64 image data.
     * @returns {string|null} Data URL for the image or null
     */
    get imageUrl() {
        const value = this.props.record.data[this.props.name];
        if (!value) return null;
        return `data:image/jpeg;base64,${value}`;
    }

    /**
     * Returns CSS class for secondary button styling.
     * @returns {string} CSS class name or empty string
     */
    get buttonClass() {
        return this.props.secondary ? "upload-btn-secondary" : "";
    }

    /**
     * Updates the preview URL based on current image state.
     */
    updatePreview() {
        if (this.hasImage) {
            this.state.previewUrl = this.imageUrl;
        } else {
            this.state.previewUrl = null;
        }
    }

    /**
     * Triggers the hidden file input when the button is clicked.
     */
    onButtonClick() {
        this.fileInputRef.el?.click();
    }

    /**
     * Handles file selection from the file input.
     * Reads the file as base64 and updates the record.
     * @param {Event} ev - The change event from file input
     */
    async onFileChange(ev) {
        const file = ev.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64 = e.target.result.split(",")[1];
            await this.props.record.update({ [this.props.name]: base64 });
            this.state.previewUrl = e.target.result;
        };
        reader.readAsDataURL(file);

        ev.target.value = "";
    }

    /**
     * Clears the uploaded image when the clear button is clicked.
     * @param {MouseEvent} ev - The click event
     */
    async onClearClick(ev) {
        ev.stopPropagation();
        await this.props.record.update({ [this.props.name]: false });
        this.state.previewUrl = null;
    }
}

ImageUploadButton.template = "onecore_maintenance_extension.ImageUploadButton";

// Register the field widget
registry.category("fields").add("image_upload_button", {
    component: ImageUploadButton,
    supportedTypes: ["binary"],
    extractProps: ({ attrs }) => ({
        secondary: attrs.secondary === "true" || attrs.secondary === "1",
    }),
});
