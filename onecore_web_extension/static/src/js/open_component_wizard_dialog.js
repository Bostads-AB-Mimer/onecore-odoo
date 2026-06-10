/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

/**
 * Opens the component wizard ("Uppdatera/lägg till Komponent") for a
 * maintenance request.
 *
 * Called after a stage change to "Utförd" has been committed when the user
 * answered Ja to the component question, and never before — the wizard must
 * not block or precede the stage write.
 *
 * @param {Object} orm - the "orm" service
 * @param {Object} actionService - the "action" service
 * @param {Object|null} notificationService - the "notification" service
 * @param {number} resId - maintenance.request id
 * @param {Object|null} uiService - the "ui" service (for the loading overlay)
 */
export async function openComponentWizardDialog(
  orm,
  actionService,
  notificationService,
  resId,
  uiService
) {
  // Loading the apartment's components from OneCore can take several seconds;
  // block the UI with a message so the user sees the wizard is on its way
  // (without this it reads as "nothing happened" after answering Ja).
  uiService?.block({ message: _t("Laddar komponenter…") });
  try {
    const action = await orm.call(
      "maintenance.request",
      "open_component_wizard",
      [[resId]]
    );
    if (action) {
      await actionService.doAction(action);
    }
  } catch (e) {
    // The stage change already succeeded — never surface this as a blocking
    // error, just let the user know the wizard could not be opened.
    console.error("Failed to open component wizard", e);
    if (notificationService) {
      notificationService.add(_t("Kunde inte öppna komponentguiden."), {
        type: "warning",
      });
    }
  } finally {
    uiService?.unblock();
  }
}
