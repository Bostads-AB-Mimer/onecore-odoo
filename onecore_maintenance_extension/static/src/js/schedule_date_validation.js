/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * Ask for confirmation when a maintenance request ends up with a planned
 * execution date (schedule_date) later than its deadline (due_date).
 *
 * Patched on Record rather than on DateTimeField because the field commits its
 * value from a closure inside setup(), which a prototype patch cannot reach.
 * Going through Record.update also covers list view inline edits.
 *
 * Only direct edits of the two date fields prompt. A priority_expanded change
 * that recomputes due_date backwards arrives via the onchange result rather
 * than the change set, and is surfaced by the schedule_date_after_due_date
 * warning in the form and kanban instead.
 */

const SCHEDULE_DATE = "schedule_date";
const DUE_DATE = "due_date";

/**
 * Compares calendar dates rather than timestamps, mirroring
 * _compute_schedule_date_after_due_date: a time of day on the due date itself
 * is not a breach.
 */
function isPlannedAfterDue(scheduleDate, dueDate) {
    // Both are luxon DateTime or false. The startOf check keeps this total:
    // update() is patched for every record, so a throw here would break all
    // date editing rather than just the warning.
    if (typeof scheduleDate?.startOf !== "function") {
        return false;
    }
    if (typeof dueDate?.startOf !== "function") {
        return false;
    }
    return scheduleDate.startOf("day") > dueDate.startOf("day");
}

/**
 * Whether `record` ends up planned after its deadline once `changes` is applied.
 */
function breachesDueDate(record, changes) {
    // ?? rather than ||: clearing a date yields false, which has to win over the
    // stored value so that clearing never trips the warning.
    return isPlannedAfterDue(
        changes[SCHEDULE_DATE] ?? record.data[SCHEDULE_DATE],
        changes[DUE_DATE] ?? record.data[DUE_DATE]
    );
}

patch(Record.prototype, {
    async update(changes, options) {
        const touchesDates = SCHEDULE_DATE in changes || DUE_DATE in changes;

        if (this.resModel === "maintenance.request" && touchesDates) {
            // Multi-edit applies the change to every selected record
            // (Record._update -> DynamicList._multiSave), so the breach has to be
            // looked for across the whole selection rather than only in the row
            // whose editor was opened.
            const records =
                this.selected && this.model.multiEdit
                    ? this.model.root.selection ?? [this]
                    : [this];

            if (records.some((record) => breachesDueDate(record, changes))) {
                const confirmed = await this._confirmScheduleDateAfterDueDate(
                    SCHEDULE_DATE in changes
                );
                if (!confirmed) {
                    return;
                }
            }
        }

        return super.update(changes, options);
    },

    /**
     * @param {boolean} scheduleDateEdited which date the user just set, so the
     *  message describes the edit they made rather than the other field
     * @returns {Promise<boolean>}
     */
    _confirmScheduleDateAfterDueDate(scheduleDateEdited) {
        const body = scheduleDateEdited
            ? _t(
                  'Observera att ditt planerade utförandedatum ligger efter förfallodatum, vill du bekräfta?'
              )
            : _t(
                  'Observera att förfallodatumet ligger före det planerade utförandedatumet, vill du bekräfta?'
              );

        return new Promise((resolve) => {
            this.model.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Observera"),
                body,
                confirm: () => resolve(true),
                cancel: () => resolve(false),
                confirmLabel: _t("Bekräfta"),
                cancelLabel: _t("Avbryt"),
            });
        });
    },
});
