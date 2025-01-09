/** @odoo-module **/
import { _t } from '@web/core/l10n/translation'
import { RelationalModel } from '@web/model/relational_model/relational_model'
import { registry } from '@web/core/registry'
import { MobileRenderer } from './mobile_renderer'
import { MobileController } from './mobile_controller'
import { MobileArchParser } from './mobile_arch_parser'

export const mobileView = {
  type: 'mobile',
  display_name: _t('Mobile'),
  icon: 'fa fa-mobile',
  multiRecord: true,
  Controller: MobileController,
  Renderer: MobileRenderer,
  ArchParser: MobileArchParser,
  Model: RelationalModel,
  /**
   * Function that returns the props for the mobile view.
   * @param {object} genericProps - Generic properties of the view.
   * @param {object} view - The view object.
   * @returns {object} Props for the mobile view.
   */
  props: (genericProps, view) => {
    const { ArchParser, Renderer } = view
    const { arch, relatedModels, resModel } = genericProps
    const archInfo = new ArchParser().parse(arch, relatedModels, resModel)
    const defaultGroupBy =
      genericProps.searchMenuTypes.includes('groupBy') &&
      archInfo.defaultGroupBy
    return {
      ...genericProps,
      archInfo,
      Model: view.Model,
      Renderer,
      defaultGroupBy,
    }
  },
}
// Register the mobile view configuration
registry.category('views').add('mobile', mobileView)
