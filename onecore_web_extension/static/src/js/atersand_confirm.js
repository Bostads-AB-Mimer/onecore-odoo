/** @odoo-module **/

import ConfirmDialog from "./confirm_dialog";

/**
 * MIM-486: all users confirm before returning a request — the move hands the
 * request back to the team that originally created it, not the team the
 * request most recently passed through, which is easy to assume and not what
 * actually happens. Naming the real destination here (from
 * preview_atersand_team, a read-only mirror of the routing write() does) lets
 * people catch that mismatch before it commits.
 *
 * Shared by the form statusbar and the kanban drag (MIM-2058) so both entry
 * points into Återsänd show the same text.
 *
 * @param {Object} orm - The orm service
 * @param {Object} dialogService - The dialog service
 * @param {number} resId - The maintenance request id
 * @param {number} stageId - The target stage id
 * @returns {Promise<boolean>} - true if the user confirms
 */
export const confirmAtersand = async (orm, dialogService, resId, stageId) => {
  const teamName = await orm.call(
    "maintenance.request",
    "preview_atersand_team",
    [[resId], stageId]
  );
  const body = teamName
    ? `Ärendet skickas till ${teamName} — det är gruppen som ursprungligen skapade ärendet, inte den grupp du senast jobbat med det i.

Vill du i stället att en specifik grupp ska ta över? Byt Resursgrupp direkt i stället för att återsända.`
    : "Är du säker på att du vill återsända ärendet?";
  return ConfirmDialog(dialogService, "Bekräfta återsändning", body);
};
