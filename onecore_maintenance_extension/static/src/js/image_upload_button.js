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

    get hasImage() {
        return Boolean(this.props.record.data[this.props.name]);
    }

    get imageUrl() {
        const value = this.props.record.data[this.props.name];
        if (!value) return null;
        // Binary field value is base64 string
        return `data:image/jpeg;base64,${value}`;
    }

    get buttonClass() {
        return this.props.secondary ? "upload-btn-secondary" : "";
    }

    updatePreview() {
        if (this.hasImage) {
            this.state.previewUrl = this.imageUrl;
        } else {
            this.state.previewUrl = null;
        }
    }

    onButtonClick() {
        this.fileInputRef.el?.click();
    }

    async onFileChange(ev) {
        const file = ev.target.files?.[0];
        if (!file) return;

        // Read file as base64
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64 = e.target.result.split(",")[1]; // Remove data:image/...;base64, prefix

            // Update the field value
            await this.props.record.update({ [this.props.name]: base64 });

            // Update preview
            this.state.previewUrl = e.target.result;
        };
        reader.readAsDataURL(file);

        // Reset input so same file can be selected again
        ev.target.value = "";
    }

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
