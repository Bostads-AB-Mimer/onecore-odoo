/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";
import { onPatched, onMounted } from "@odoo/owl";

patch(FormRenderer.prototype, {
  setup() {
    super.setup();
    this._openAccordionIds = new Set();

    const restoreAccordions = () => {
      for (const id of this._openAccordionIds) {
        const el = document.getElementById(id);
        if (el && !el.classList.contains("show")) {
          el.classList.add("show");
          // Update the button's aria-expanded and collapsed class
          const button = document.querySelector(
            `[data-bs-target="#${id}"]`
          );
          if (button) {
            button.classList.remove("collapsed");
            button.setAttribute("aria-expanded", "true");
          }
        }
      }
    };

    onMounted(() => {
      this._bindAccordionListeners();
      restoreAccordions();
    });

    onPatched(() => {
      this._bindAccordionListeners();
      restoreAccordions();
    });
  },

  _bindAccordionListeners() {
    const accordion = document.getElementById("accordionFlush");
    if (!accordion || accordion._accordionListenersBound) return;
    accordion._accordionListenersBound = true;

    accordion.addEventListener("shown.bs.collapse", (ev) => {
      if (ev.target.id) {
        this._openAccordionIds.add(ev.target.id);
      }
    });
    accordion.addEventListener("hidden.bs.collapse", (ev) => {
      if (ev.target.id) {
        this._openAccordionIds.delete(ev.target.id);
      }
    });
  },
});
