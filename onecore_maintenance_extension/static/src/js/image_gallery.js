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

    /**
     * Parses the JSON field value and returns an array of valid image URLs.
     * @returns {string[]} Array of image URLs
     */
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

    /**
     * Checks if the gallery has any images to display.
     * @returns {boolean} True if there are images
     */
    get hasImages() {
        return this.imageUrls.length > 0;
    }

    /**
     * Returns the configured thumbnail height in pixels.
     * @returns {number} Thumbnail height (default: 100)
     */
    get thumbnailHeight() {
        return this.props.thumbnailSize || 100;
    }

    /**
     * Returns the URL of the currently displayed fullscreen image.
     * @returns {string|null} Current image URL or null
     */
    get currentFullscreenUrl() {
        const urls = this.imageUrls;
        if (urls.length > 0 && this.state.fullscreenIndex < urls.length) {
            return urls[this.state.fullscreenIndex];
        }
        return null;
    }

    /**
     * Checks if navigation between images is possible (more than one image).
     * @returns {boolean} True if navigation is available
     */
    get canNavigate() {
        return this.imageUrls.length > 1;
    }

    /**
     * Returns a formatted string showing the current image position.
     * @returns {string} Image counter (e.g., "1 / 5")
     */
    get imageCounter() {
        return `${this.state.fullscreenIndex + 1} / ${this.imageUrls.length}`;
    }

    /**
     * Opens fullscreen view for the image at the given index.
     * @param {number} index - The index of the image to display
     */
    openFullscreen(index) {
        if (this.hasImages) {
            this.state.fullscreenIndex = index;
            this.state.isFullscreen = true;
        }
    }

    /**
     * Closes the fullscreen view.
     */
    closeFullscreen() {
        this.state.isFullscreen = false;
    }

    /**
     * Navigates to the previous image in the gallery (wraps around).
     */
    previousImage() {
        const urls = this.imageUrls;
        if (urls.length > 1) {
            this.state.fullscreenIndex = (this.state.fullscreenIndex - 1 + urls.length) % urls.length;
        }
    }

    /**
     * Navigates to the next image in the gallery (wraps around).
     */
    nextImage() {
        const urls = this.imageUrls;
        if (urls.length > 1) {
            this.state.fullscreenIndex = (this.state.fullscreenIndex + 1) % urls.length;
        }
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
     * Handles click on the previous button.
     * @param {MouseEvent} ev - The click event
     */
    onPrevClick(ev) {
        ev.stopPropagation();
        this.previousImage();
    }

    /**
     * Handles click on the next button.
     * @param {MouseEvent} ev - The click event
     */
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
