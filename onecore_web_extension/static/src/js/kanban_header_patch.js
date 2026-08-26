/* @odoo-module */

import { patch } from "@web/core/utils/patch";
import { KanbanHeader } from "@web/views/kanban/kanban_header";

patch(KanbanHeader.prototype, {
  /**
   * Override configMenuProps to remove the edit and delete group
   * options from the dropdown menu, for ALL USERS.
   *
   * This prevents users from editing or deleting kanban groups.
   *
   * Note: the maintenance request kanban additionally sets
   * group_create/group_delete="false" in its arch
   * (onecore_maintenance_extension, hr_equipment_request_view_kanban_extension),
   * so removing this patch does not re-enable column delete there — but it
   * WOULD re-enable column edit on every kanban.
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
