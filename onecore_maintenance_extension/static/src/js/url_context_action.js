/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Client action that acts as a bridge for opening the maintenance request
 * create form with context from URL parameters.
 *
 * In Odoo 19, window actions (ir.actions.act_window) no longer receive URL
 * parameters in their context. Client actions still do via action.params.
 * This action reads the context JSON from URL params and forwards it to the
 * real window action as additionalContext.
 */
async function maintenanceCreateFromUrl(env, action) {
  const params = action.params || {};
  const contextStr = params.context;
  let additionalContext = {};

  if (typeof contextStr === "string") {
    try {
      additionalContext = JSON.parse(contextStr);
    } catch (e) {
      console.warn("Failed to parse maintenance request context from URL:", e);
    }
  }

  await env.services.action.doAction(
    "onecore_maintenance_extension.action_maintenance_request_create",
    { additionalContext, clearBreadcrumbs: true }
  );
}

registry
  .category("actions")
  .add("maintenance_create_from_url", maintenanceCreateFromUrl);
