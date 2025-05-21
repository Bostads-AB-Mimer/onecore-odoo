/* @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { KanbanHeader } from "@web/views/kanban/kanban_header";

patch(KanbanHeader.prototype, {
  setup() {
    super.setup();
  },

  /**
   * @override
   */

  get configItems() {
    /**
     *
     * Modifying the kanban header config items to remove the edit and delete group
     * options from the dropdown menu, for ALL USERS.
     *
     * This is done to prevent users from editing or deleting the kanban group
     */

    const args = { permissions: this.permissions, props: this.props };
    return registry
      .category("kanban_header_config_items")
      .getEntries()
      .filter(
        ([_, desc]) =>
          desc.method !== "editGroup" && desc.method !== "deleteGroup"
      )
      .map(([key, desc]) => ({
        key,
        method: desc.method,
        label: desc.label,
        isVisible:
          typeof desc.isVisible === "function"
            ? desc.isVisible(args)
            : desc.isVisible,
        class: typeof desc.class === "function" ? desc.class(args) : desc.class,
      }));
  },
});
