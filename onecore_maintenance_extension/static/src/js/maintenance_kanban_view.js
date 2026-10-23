/** @odoo-module **/

import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { Group } from "@web/model/relational_model/group";

/**
 * Maintenance request kanban whose folded/unfolded stage columns are
 * remembered per browser (localStorage), not per user and not in the
 * database — maintenance.stage.fold is shared by everyone.
 *
 * The stored map is sent to the server as the onecore_kanban_fold context
 * key; MaintenanceRequest._web_read_group_format applies it on top of the
 * default (everything unfolded except Återsänd).
 */
const STORAGE_KEY = "onecore.maintenance.kanban.fold";
const STAGE_FIELD = "stage_id";

/** @returns {Object<string, boolean>} */
function readFoldState() {
  try {
    const parsed = JSON.parse(browser.localStorage.getItem(STORAGE_KEY));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : {};
  } catch {
    return {};
  }
}

function writeFoldState(stageId, isFolded) {
  try {
    const state = readFoldState();
    state[stageId] = isFolded;
    browser.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage blocked (private mode etc.): the server default applies.
  }
}

class MaintenanceKanbanGroup extends Group {
  async toggle() {
    await super.toggle();
    if (this.groupByField?.name === STAGE_FIELD && this.value) {
      writeFoldState(this.value, this.isFolded);
    }
  }
}

class MaintenanceKanbanModel extends RelationalModel {
  static Group = MaintenanceKanbanGroup;

  async _webReadGroup(config, cache) {
    if (config.groupBy?.[0] !== STAGE_FIELD) {
      return super._webReadGroup(config, cache);
    }
    // Only for this call: the key must not leak into record/group contexts.
    const context = config.context;
    config.context = { ...context, onecore_kanban_fold: readFoldState() };
    try {
      return await super._webReadGroup(config, cache);
    } finally {
      config.context = context;
    }
  }
}

registry.category("views").add("onecore_maintenance_request_kanban", {
  ...kanbanView,
  Model: MaintenanceKanbanModel,
});
