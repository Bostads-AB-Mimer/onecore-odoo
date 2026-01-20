/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, useEffect } from "@odoo/owl";

/**
 * Image gallery widget for displaying multiple images in a 3-column grid.
 * Parses a JSON array of image URLs and renders them with fullscreen capability.
 * Optimized for mobile users with responsive layout and large touch targets.
 */
export class ImageGallery extends Component {
    static template = "onecore_maintenance_extension.ImageGallery";
    static props = {
        ...standardFieldProps,
        thumbnailSize: { type: Number, optional: true },
    };

    setup() {
        this.state = useState({
            isFullscreen: false,
            fullscreenIndex: 0,
        });

        // Handle escape key to close fullscreen
        useEffect(
            () => {
                const handleKeyDown = (e) => {
                    if (e.key === "Escape" && this.state.isFullscreen) {
                        this.closeFullscreen();
                    } else if (e.key === "ArrowLeft" && this.state.isFullscreen) {
                        this.previousImage();
                    } else if (e.key === "ArrowRight" && this.state.isFullscreen) {
                        this.nextImage();
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

    get imageUrls() {
        const value = this.props.record.data[this.props.name];
        if (!value) return [];

        try {
            const urls = JSON.parse(value);
            return Array.isArray(urls) ? urls.filter(url => url) : [];
        } catch (e) {
            return [];
        }
    }

    get hasImages() {
        return this.imageUrls.length > 0;
    }

    get thumbnailHeight() {
        return this.props.thumbnailSize || 100;
    }

    get currentFullscreenUrl() {
        const urls = this.imageUrls;
        if (urls.length > 0 && this.state.fullscreenIndex < urls.length) {
            return urls[this.state.fullscreenIndex];
        }
        return null;
    }

    get canNavigate() {
        return this.imageUrls.length > 1;
    }

    get imageCounter() {
        return `${this.state.fullscreenIndex + 1} / ${this.imageUrls.length}`;
    }

    openFullscreen(index) {
        if (this.hasImages) {
            this.state.fullscreenIndex = index;
            this.state.isFullscreen = true;
        }
    }

    closeFullscreen() {
        this.state.isFullscreen = false;
    }

    previousImage() {
        const urls = this.imageUrls;
        if (urls.length > 1) {
            this.state.fullscreenIndex = (this.state.fullscreenIndex - 1 + urls.length) % urls.length;
        }
    }

    nextImage() {
        const urls = this.imageUrls;
        if (urls.length > 1) {
            this.state.fullscreenIndex = (this.state.fullscreenIndex + 1) % urls.length;
        }
    }

    onOverlayClick(ev) {
        // Close when clicking on the overlay background (not the image or controls)
        if (ev.target.classList.contains("image-fullscreen-overlay")) {
            this.closeFullscreen();
        }
    }

    onImageClick(ev) {
        // Prevent closing when clicking on the image itself
        ev.stopPropagation();
    }

    onPrevClick(ev) {
        ev.stopPropagation();
        this.previousImage();
    }

    onNextClick(ev) {
        ev.stopPropagation();
        this.nextImage();
    }
}

// Register the field widget
registry.category("fields").add("image_gallery", {
    component: ImageGallery,
    supportedTypes: ["text", "char"],
    extractProps: ({ attrs }) => ({
        thumbnailSize: attrs.thumbnailSize ? parseInt(attrs.thumbnailSize, 10) : 100,
    }),
});
