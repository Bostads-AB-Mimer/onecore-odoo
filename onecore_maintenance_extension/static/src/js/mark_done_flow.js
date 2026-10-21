/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { RPCError } from "@web/core/network/rpc";
import { Dialog } from "@web/core/dialog/dialog";
import {
    AlertDialog,
    ConfirmationDialog,
} from "@web/core/confirmation_dialog/confirmation_dialog";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, status, useEffect, useRef, useState } from "@odoo/owl";

const DRAFT_PREFIX = "onecore_mark_done:";
const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Removes stored answers older than a week, for every ärende and user on this
 * device. Storage can be blocked or full: the flow then runs without it.
 */
function removeOldDrafts() {
    try {
        const storage = browser.localStorage;
        const old = [];
        for (let i = 0; i < storage.length; i++) {
            const key = storage.key(i);
            if (!key?.startsWith(DRAFT_PREFIX)) {
                continue;
            }
            let savedAt = 0;
            try {
                savedAt = JSON.parse(storage.getItem(key))?.savedAt || 0;
            } catch {
                savedAt = 0;
            }
            if (Date.now() - savedAt > DRAFT_MAX_AGE_MS) {
                old.push(key);
            }
        }
        for (const key of old) {
            storage.removeItem(key);
        }
    } catch {
        // Storage blocked
    }
}

/**
 * "Markera som utförd": a step per component (outcome and note), then a
 * summary whose Spara registers the outcomes and moves the ärende to Utförd.
 */
export class MarkDoneDialog extends Component {
    static template = "onecore_maintenance_extension.MarkDoneDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        resId: Number,
        // [{id, name, subtype_name, space_name, note, outcomes: [[key, label]],
        //   outcome, outcome_note}]
        components: Array,
        contractor: Boolean,
        onSaved: Function,
        // Called with the server's message; resolves to true when the ärende
        // can no longer be marked as utförd
        onRefused: Function,
    };

    setup() {
        // Not useService: a save must still settle after the dialog closes
        this.orm = this.env.services.orm;
        this.bodyRef = useRef("body");
        this.draftKey = `${DRAFT_PREFIX}${user.userId}:${this.props.resId}`;
        removeOldDrafts();
        this.state = useState({
            answers: { ...this.storedAnswers(), ...this.readDraft() },
            index: 0,
            saving: false,
            error: "",
        });
        this.state.index = this.firstOpenStepIndex();
        this.writeDraftSoon = useDebounced(this.writeDraft, 300, { execBeforeUnmount: true });

        // Each step starts at the top. Block body: scrollTo can return a promise
        useEffect(
            () => {
                this.bodyRef.el?.closest(".modal-body")?.scrollTo(0, 0);
            },
            () => [this.state.index]
        );
    }

    /** A step per component, then the summary, which has Spara. */
    get steps() {
        const steps = this.props.components.map((component, position) => ({
            kind: "component",
            component,
            position,
        }));
        steps.push({ kind: "summary", final: true });
        return steps;
    }

    get step() {
        const steps = this.steps;
        return steps[Math.min(this.state.index, steps.length - 1)];
    }

    get isFirstStep() {
        return this.state.index === 0;
    }

    get progressPercent() {
        const { position } = this.step;
        return Math.round(((position + 1) / this.props.components.length) * 100);
    }

    get canGoNext() {
        const step = this.step;
        return step.kind !== "component" || Boolean(this.answerFor(step.component).outcome);
    }

    get canSave() {
        if (this.state.saving) {
            return false;
        }
        return this.props.components.every((component) => this.answerFor(component).outcome);
    }

    answerFor(component) {
        return this.state.answers[component.id] || { outcome: false, note: "" };
    }

    outcomeLabel(component) {
        const outcome = this.answerFor(component).outcome;
        const option = component.outcomes.find(([key]) => key === outcome);
        return option ? option[1] : "Inget utfall valt";
    }

    firstOpenStepIndex() {
        const index = this.steps.findIndex(
            (step) => step.kind === "component" && !this.answerFor(step.component).outcome
        );
        return index === -1 ? this.steps.length - 1 : index;
    }

    selectOutcome(component, outcome) {
        this.state.answers[component.id] = { ...this.answerFor(component), outcome };
        this.writeDraft();
    }

    setNote(component, note) {
        this.state.answers[component.id] = { ...this.answerFor(component), note };
        this.writeDraftSoon();
    }

    goTo(index) {
        if (this.state.saving) {
            return;
        }
        this.state.error = "";
        this.state.index = Math.max(0, Math.min(index, this.steps.length - 1));
    }

    previous() {
        this.goTo(this.state.index - 1);
    }

    next() {
        if (this.canGoNext) {
            this.goTo(this.state.index + 1);
        }
    }

    async save() {
        if (!this.canSave) {
            return;
        }
        const { components, resId } = this.props;
        const outcomes = components.map((component) => ({
            id: component.id,
            outcome: this.answerFor(component).outcome,
            note: this.answerFor(component).note || "",
        }));
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.orm.call("maintenance.request", "action_register_outcomes", [
                [resId],
                outcomes,
            ]);
        } catch (error) {
            if (error instanceof RPCError && error.exceptionName?.startsWith("odoo.exceptions.")) {
                await this.refused(error.data?.message || "Kunde inte spara.");
                return;
            }
            if (status(this) !== "destroyed") {
                this.state.saving = false;
            }
            throw error;
        }
        this.clearDraft();
        if (status(this) !== "destroyed") {
            this.props.close();
        }
        await this.props.onSaved();
    }

    /**
     * Spara was refused: drop the answers and close when the ärende can no
     * longer be marked as utförd, otherwise show the message.
     */
    async refused(message) {
        let closed = false;
        try {
            closed = await this.props.onRefused(message);
        } finally {
            if (closed) {
                this.clearDraft();
                if (status(this) !== "destroyed") {
                    this.props.close();
                }
            } else if (status(this) !== "destroyed") {
                this.state.saving = false;
                this.state.error = message;
            }
        }
    }

    // Answers: the stored outcomes, overridden by a draft in localStorage for
    // components whose stored outcome hasn't changed since the draft

    /** A component's stored outcome, as kept in the draft. */
    storedOf(component) {
        return JSON.stringify([component.outcome || false, component.outcome_note || ""]);
    }

    /** The answer for a component if it is still on the ärende and offered. */
    validAnswer(component, saved) {
        if (!saved || typeof saved !== "object") {
            return null;
        }
        const offered = component.outcomes.some(([key]) => key === saved.outcome);
        return {
            outcome: offered ? saved.outcome : false,
            note: typeof saved.note === "string" ? saved.note : "",
        };
    }

    storedAnswers() {
        const answers = {};
        for (const component of this.props.components) {
            if (component.outcome || component.outcome_note) {
                answers[component.id] = this.validAnswer(component, {
                    outcome: component.outcome,
                    note: component.outcome_note,
                });
            }
        }
        return answers;
    }

    readDraft() {
        let draft = null;
        try {
            draft = JSON.parse(browser.localStorage.getItem(this.draftKey) || "null");
        } catch {
            draft = null;
        }
        const answers = {};
        if (!draft || typeof draft !== "object") {
            return answers;
        }
        for (const component of this.props.components) {
            // Someone saved an outcome for it since: that answer is stale
            if (draft.stored?.[component.id] !== this.storedOf(component)) {
                continue;
            }
            const answer = this.validAnswer(component, draft.answers?.[component.id]);
            if (answer) {
                answers[component.id] = answer;
            }
        }
        return answers;
    }

    writeDraft() {
        try {
            browser.localStorage.setItem(
                this.draftKey,
                JSON.stringify({
                    answers: this.state.answers,
                    stored: Object.fromEntries(
                        this.props.components.map((component) => [
                            component.id,
                            this.storedOf(component),
                        ])
                    ),
                    savedAt: Date.now(),
                })
            );
        } catch {
            // Storage blocked or full
        }
    }

    clearDraft() {
        this.writeDraftSoon.cancel();
        try {
            browser.localStorage.removeItem(this.draftKey);
        } catch {
            // Storage blocked
        }
    }
}

/** The "Markera som utförd" button in the form header. */
export class MarkDoneButton extends Component {
    static template = "onecore_maintenance_extension.MarkDoneButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ busy: false });
    }

    async onClick() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            await this.open();
        } finally {
            this.state.busy = false;
        }
    }

    async open() {
        const record = this.props.record;
        if (await record.isDirty()) {
            if (!(await this.confirmSave()) || !(await record.save())) {
                return;
            }
        }
        const resId = record.resId;
        const check = await this.orm.call("maintenance.request", "check_can_mark_done", [
            [resId],
        ]);
        // Paged to another ärende while the check ran
        if (this.props.record.resId !== resId) {
            return;
        }
        if (check.error) {
            // Shows the ärende as it is now, e.g. already Utförd from elsewhere
            if (await this.canReload(resId)) {
                await this.reload(resId);
            }
            this.dialog.add(AlertDialog, {
                title: "Kan inte markera som utförd",
                body: check.error,
            });
            return;
        }
        this.dialog.add(MarkDoneDialog, {
            resId,
            components: check.components,
            contractor: check.contractor,
            onSaved: () => this.onSaved(resId),
            onRefused: (message) => this.onRefused(resId, message),
        });
    }

    confirmSave() {
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: "Osparade ändringar",
                body: "Ärendet har ändringar som inte är sparade. Spara dem och fortsätt?",
                confirmLabel: "Spara och fortsätt",
                cancelLabel: "Avbryt",
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
    }

    // Called by the dialog, also after the button is gone (left the form, or
    // hidden by a reload)

    /** Whether the form shows this ärende with no unsaved changes to lose. */
    async canReload(resId) {
        const record = this.props.record;
        return (
            status(this) !== "destroyed" && record.resId === resId && !(await record.isDirty())
        );
    }

    /**
     * Reloads the form and its chatter. Record.load() leaves the chatter as
     * it was; only a model load tells it to fetch new messages.
     */
    async reload(resId) {
        await this.props.record.load();
        this.env.bus.trigger("MAIL:RELOAD-THREAD", { model: "maintenance.request", id: resId });
    }

    async onSaved(resId) {
        this.notification.add("Ärendet är markerat som utfört.", { type: "success" });
        // Stage, read-only fields and this button follow from the new stage
        if (await this.canReload(resId)) {
            await this.reload(resId);
        }
    }

    async onRefused(resId, message) {
        const record = this.props.record;
        if (!(await this.canReload(resId))) {
            return false;
        }
        await this.reload(resId);
        if (record.data.can_mark_done) {
            return false;
        }
        this.notification.add(message, { type: "warning" });
        return true;
    }
}

registry.category("view_widgets").add("mark_done_button", {
    component: MarkDoneButton,
    fieldDependencies: [{ name: "can_mark_done", type: "boolean" }],
});
