/** @odoo-module **/

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

// This patch is used to prevent external contractors from creating maintenance requests
// using the button in the kanban view.

patch(KanbanController.prototype, {
  setup(env, services) {
    super.setup(env, services);
    this.rpc = useService("rpc");
    this.isExternalContractor;

    onWillStart(async () => {
      const isExternalContractor = await this.rpc("/web/dataset/call_kw", {
        model: "maintenance.request",
        method: "is_user_external_contractor",
        args: [],
        kwargs: {},
      });
      this.isExternalContractor = isExternalContractor;
    });
  },
  get canCreate() {
    const { create, createGroup } = this.props.archInfo.activeActions;
    const list = this.model.root;
    if (this.isExternalContractor) return false;

    if (!create) {
      return false;
    }
    if (list.isGrouped) {
      if (list.groupByField.type !== "many2one") {
        return true;
      }
      return list.groups.length || !createGroup;
    }
    return true;
  },
});
