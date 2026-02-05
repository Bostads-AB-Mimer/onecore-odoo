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

    /**
     * Checks if the field contains valid image data.
     * Handles both binary data and URL strings.
     * @returns {boolean} True if image data exists
     */
    get hasImage() {
        const value = this.props.record.data[this.props.name];
        if (typeof value === 'string' && value.length > 0) {
            return true;
        }
        if (value && this.props.record.resId) {
            return true;
        }
        return false;
    }

    /**
     * Computes the image source URL based on field type and value.
     * Supports binary data, data URLs, HTTP URLs, and Odoo image endpoints.
     * @returns {string|null} Image source URL or null
     */
    get imageSrc() {
        const value = this.props.record.data[this.props.name];
        if (!value) return null;

        const field = this.props.record.fields[this.props.name];
        const fieldType = field ? field.type : 'binary';

        if (typeof value === 'string' && value.length > 0) {
            if (fieldType === 'char') {
                return value;
            }

            if (value.startsWith('data:')) {
                return value;
            }
            if (value.startsWith('http://') || value.startsWith('https://')) {
                return value;
            }
            if (value.length > 100) {
                return `data:image/png;base64,${value}`;
            }
        }

        const record = this.props.record;
        if (record.resId && fieldType === 'binary') {
            return `/web/image/${record.resModel}/${record.resId}/${this.props.name}?t=${Date.now()}`;
        }

        return null;
    }

    /**
     * Returns the configured thumbnail height in pixels.
     * @returns {number} Thumbnail height (default: 80)
     */
    get thumbnailHeight() {
        return this.props.thumbnailSize || 80;
    }

    /**
     * Opens the fullscreen image viewer.
     */
    openFullscreen() {
        if (this.hasImage) {
            this.state.isFullscreen = true;
        }
    }

    /**
     * Closes the fullscreen image viewer.
     */
    closeFullscreen() {
        this.state.isFullscreen = false;
    }

    /**
     * Handles click on the fullscreen overlay background.
     * Closes fullscreen when clicking outside the image.
     * @param {MouseEvent} ev - The click event
     */
    onOverlayClick(ev) {
        if (ev.target.classList.contains("image-fullscreen-overlay")) {
            this.closeFullscreen();
        }
    }

    /**
     * Handles click on the fullscreen image itself.
     * Prevents the overlay click handler from closing the view.
     * @param {MouseEvent} ev - The click event
     */
    onImageClick(ev) {
        ev.stopPropagation();
    }

    /**
     * Handles image load errors by logging debug information.
     * @param {Event} ev - The error event
     */
    onImageError(ev) {
        const value = this.props.record.data[this.props.name];
        console.error('Image failed to load:', {
            fieldName: this.props.name,
            valueType: typeof value,
            valueLength: typeof value === 'string' ? value.length : 'N/A',
            valuePreview: typeof value === 'string' ? value.substring(0, 50) + '...' : value,
            computedSrc: this.imageSrc?.substring(0, 100) + '...',
        });
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
