import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * New ticket page in the portal: the form select only offers the forms of
 * the chosen category (preselected when there is one), and only the
 * fieldset of the chosen form is visible and enabled. Hidden fieldsets are
 * disabled so their inputs are neither validated by the browser nor posted.
 */
export class NewTicketForm extends Interaction {
    static selector = "form[action='/submitted/ticket']";
    dynamicContent = {
        "select[name='category']": { "t-on-change": this.onCategoryChange },
        "select[name='form']": { "t-on-change": this.onFormChange },
    };

    setup() {
        this.categorySelect = this.el.querySelector("select[name='category']");
        this.formSelect = this.el.querySelector("select[name='form']");
        this.formGroup = this.el.querySelector("#onecore_form_group");
        this.fieldsets = [...this.el.querySelectorAll("fieldset[data-form-id]")];
        this.categoryFieldsets = [...this.el.querySelectorAll("fieldset[data-category-id]")];
    }

    start() {
        this.onCategoryChange();
    }

    onCategoryChange() {
        const categoryId = this.categorySelect?.value || "";
        // the category's common questions, whichever form is chosen
        for (const fieldset of this.categoryFieldsets) {
            const active = fieldset.dataset.categoryId === categoryId;
            fieldset.disabled = !active;
            fieldset.classList.toggle("d-none", !active);
        }
        if (!this.formSelect) {
            return;
        }
        const matching = [];
        for (const option of this.formSelect.options) {
            if (!option.value) {
                continue;
            }
            const match = option.dataset.categoryId === categoryId;
            option.hidden = !match;
            option.disabled = !match;
            if (match) {
                matching.push(option);
            }
        }
        const current = this.formSelect.value;
        if (current && !matching.some((option) => option.value === current)) {
            this.formSelect.value = "";
        }
        if (matching.length === 1) {
            this.formSelect.value = matching[0].value;
        }
        this.formGroup?.classList.toggle("d-none", matching.length === 0);
        this.formSelect.required = matching.length > 0;
        this.onFormChange();
    }

    onFormChange() {
        const formId = this.formSelect?.value || "";
        for (const fieldset of this.fieldsets) {
            const active = fieldset.dataset.formId === formId;
            fieldset.disabled = !active;
            fieldset.classList.toggle("d-none", !active);
        }
    }
}

registry.category("public.interactions").add("onecore_helpdesk.new_ticket_form", NewTicketForm);
