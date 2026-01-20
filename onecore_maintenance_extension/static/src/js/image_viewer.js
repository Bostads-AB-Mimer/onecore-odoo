/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, useEffect } from "@odoo/owl";

/**
 * Custom image viewer component with fullscreen capability.
 * Shows a clickable thumbnail that expands to fullscreen view.
 * Optimized for mobile users with large touch targets.
 */
export class ImageViewer extends Component {
    static template = "onecore_maintenance_extension.ImageViewer";
    static props = {
        ...standardFieldProps,
        thumbnailSize: { type: Number, optional: true },
    };

    setup() {
        this.state = useState({
            isFullscreen: false,
        });

        // Handle escape key to close fullscreen
        useEffect(
            () => {
                const handleKeyDown = (e) => {
                    if (e.key === "Escape" && this.state.isFullscreen) {
                        this.closeFullscreen();
                    }
                };
                document.addEventListener("keydown", handleKeyDown);
                return () => {
                    document.removeEventListener("keydown", handleKeyDown);
                };
            },
            () => [this.state.isFullscreen]
        );

        // Prevent body scroll when fullscreen is open
        useEffect(
            () => {
                if (this.state.isFullscreen) {
                    document.body.style.overflow = "hidden";
                } else {
                    document.body.style.overflow = "";
                }
                return () => {
                    document.body.style.overflow = "";
                };
            },
            () => [this.state.isFullscreen]
        );
    }

    get hasImage() {
        return Boolean(this.props.record.data[this.props.name]);
    }

    get imageSrc() {
        const value = this.props.record.data[this.props.name];
        if (!value) return null;

        // Get the field type from the model
        const field = this.props.record.fields[this.props.name];
        const fieldType = field ? field.type : 'binary';

        if (typeof value === 'string') {
            // For char fields (URLs), use the value directly
            if (fieldType === 'char') {
                // Value is a URL - use it directly
                return value;
            }

            // For binary fields, handle data URLs and base64
            if (value.startsWith('data:')) {
                return value;
            }
            if (value.startsWith('http://') || value.startsWith('https://')) {
                return value;
            }
            // Raw base64 string
            return `data:image/png;base64,${value}`;
        }

        // For saved records with binary fields, use Odoo's web/image endpoint
        const record = this.props.record;
        if (record.resId && fieldType === 'binary') {
            return `/web/image/${record.resModel}/${record.resId}/${this.props.name}`;
        }

        return null;
    }

    get thumbnailHeight() {
        return this.props.thumbnailSize || 80;
    }

    openFullscreen() {
        if (this.hasImage) {
            this.state.isFullscreen = true;
        }
    }

    closeFullscreen() {
        this.state.isFullscreen = false;
    }

    onOverlayClick(ev) {
        // Close when clicking on the overlay background (not the image)
        if (ev.target.classList.contains("image-fullscreen-overlay")) {
            this.closeFullscreen();
        }
    }

    onImageClick(ev) {
        // Prevent closing when clicking on the image itself
        ev.stopPropagation();
    }
}

// Register the field widget (supports both binary and char/URL fields)
registry.category("fields").add("image_viewer", {
    component: ImageViewer,
    supportedTypes: ["binary", "char"],
    extractProps: ({ attrs }) => ({
        thumbnailSize: attrs.thumbnailSize ? parseInt(attrs.thumbnailSize, 10) : 80,
    }),
});
