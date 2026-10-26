/* @odoo-module */

import { patch } from "@web/core/utils/patch";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";

patch(SearchBarMenu.prototype, {
  /**
   * Show every shared favorite, for ALL USERS. Stock lists three and folds
   * the rest under "More..." once there are more than four, which hides some
   * of the favorites shipped for ärenden (data/ir_filters.xml in
   * onecore_maintenance_extension).
   */
  setup() {
    super.setup(...arguments);
    this.state.sharedFavoritesExpanded = true;
  },
});
