/* @odoo-module */

import { patch } from "@web/core/utils/patch";
import { KanbanHeader } from "@web/views/kanban/kanban_header";

patch(KanbanHeader.prototype, {
  /**
   * Override configMenuProps to remove the edit and delete group
   * options from the dropdown menu, for ALL USERS.
   *
   * This prevents users from editing or deleting kanban groups.
   */
  get configMenuProps() {
    const result = super.configMenuProps;
    result.configItems = result.configItems.filter(
      ([_, desc]) =>
        desc.method !== "editGroup" && desc.method !== "deleteGroup",
    );
    return result;
  },
});
