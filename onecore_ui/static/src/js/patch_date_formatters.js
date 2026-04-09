/** @odoo-module **/
/**
 * MIM-1638: Restore pre-Odoo 19 date/datetime field rendering.
 *
 * Odoo 19 changed @web/views/fields/formatters.js so that the default
 * formatDate / formatDateTime path calls toLocaleDateString /
 * toLocaleDateTimeString — which use the browser's Luxon locale and
 * strip the year when it matches the current year. This ignores
 * res.lang.date_format entirely and produces outputs like "Apr 9" or
 * "4 maj 2027" instead of "2026-04-09" / "2027-05-04".
 *
 * Override the registry entries so all date/datetime field rendering
 * goes through the lang-aware helpers from @web/core/l10n/dates that
 * still honor localization.dateFormat (derived from res.lang).
 */
import { registry } from "@web/core/registry";
import {
    formatDate as langFormatDate,
    formatDateTime as langFormatDateTime,
} from "@web/core/l10n/dates";

const formatters = registry.category("formatters");

function formatDate(value, options = {}) {
    return langFormatDate(value, options);
}
formatDate.extractOptions = () => ({});

function formatDateTime(value, options = {}) {
    if (options?.showTime === false) {
        return langFormatDate(value, options);
    }
    return langFormatDateTime(value, options);
}
formatDateTime.extractOptions = ({ options } = {}) => ({
    showSeconds: Boolean(options?.show_seconds ?? false),
    showTime: Boolean(options?.show_time ?? true),
    showDate: Boolean(options?.show_date ?? true),
});

formatters.add("date", formatDate, { force: true });
formatters.add("datetime", formatDateTime, { force: true });
