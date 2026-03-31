/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { useService } from "@web/core/utils/hooks";
import ConfirmDialog from "./confirm_dialog";

patch(StatusBarField.prototype, {
  setup() {
    super.setup();
    this.dialogService = useService("dialog");
    this.userIsExternalContractor =
      this.props.record.model.config.resModel === "maintenance.request" &&
      this.props.record.data.user_is_external_contractor;
  },

  adjustVisibleItems() {
    // Override to skip the env.isSmall check that collapses all stages
    // into a single dropdown on mobile. We want stages always visible
    // as arrow buttons. This replicates the base logic without that check.
    const hide = (...els) => els.forEach((el) => el.classList.add("d-none"));
    const show = (...els) => els.forEach((el) => el.classList.remove("d-none"));

    const itemEls = [
      ...this.rootRef.el.querySelectorAll(
        ".o_arrow_button:not(.dropdown-toggle)"
      ),
    ];
    const selectedIndex = itemEls.findIndex((el) =>
      el.classList.contains("o_arrow_button_current")
    );
    const itemsBefore = itemEls.slice(selectedIndex + 2).reverse();
    const itemsAfter = itemEls
      .slice(0, Math.max(selectedIndex - 1, 0))
      .reverse();

    show(...itemEls);
    hide(this.dropdownRef.el, this.beforeRef.el);
    if (this.items.folded.length) {
      show(this.afterRef.el);
      itemEls.forEach((el) => el.classList.remove("o_first"));
    } else {
      hide(this.afterRef.el);
      itemEls[0]?.classList.add("o_first");
    }

    this.items.before = [];
    this.items.after = [...this.items.folded];
    const itemsToAssign = this.getAllItems().filter((item) => !item.isFolded);

    // Intentionally omitted: the env.isSmall early return that hides all buttons

    while (this.areItemsWrapping()) {
      if (itemsBefore.length) {
        show(this.beforeRef.el);
        hide(itemsBefore.shift());
        this.items.before.push(itemsToAssign.shift());
      } else if (itemsAfter.length) {
        show(this.afterRef.el);
        hide(itemsAfter.pop());
        this.items.after.unshift(itemsToAssign.pop());
      } else {
        show(this.dropdownRef.el);
        hide(this.beforeRef.el, this.afterRef.el, ...itemEls);
        break;
      }
    }
  },

  getAllItems() {
    const { foldField, name, record } = this.props;
    const currentValue = record.data[name];

    if (this.field.type === "many2one") {
      // Many2one — Odoo 19 uses {id, display_name} objects instead of arrays
      const currentStageName = currentValue && currentValue.display_name;

      return this.specialData.data.map((option) => ({
        value: option.id,
        label: option.display_name,
        isFolded: option[foldField],
        isSelected: Boolean(currentValue && option.id === currentValue.id),
        isDisabled:
          (currentStageName === "Väntar på handläggning" &&
            !record.data.user_id) ||
          (this.userIsExternalContractor &&
            (option.display_name === "Avslutad" ||
              currentStageName === "Avslutad" ||
              currentStageName === "Utförd")),
      }));
    } else {
      // Selection
      let { selection } = this.field;
      const { visibleSelection } = this.props;
      if (visibleSelection?.length) {
        selection = selection.filter(
          ([value]) =>
            value === currentValue || visibleSelection.includes(value)
        );
      }
      return selection.map(([value, label]) => ({
        value,
        label,
        isFolded: false,
        isSelected: value === currentValue,
      }));
    }
  },

  async selectItem(item) {
    if (this.userIsExternalContractor && item.label === "Utförd") {
      const confirmed = await ConfirmDialog(
        this.dialogService,
        "Bekräfta ändring",
        "Är du säker på att du vill ändra statusen till Utförd? Om du gör detta kan du inte ändra tillbaka."
      );
      if (confirmed) {
        super.selectItem(item);
      }
    } else {
      super.selectItem(item);
    }
  },
});
