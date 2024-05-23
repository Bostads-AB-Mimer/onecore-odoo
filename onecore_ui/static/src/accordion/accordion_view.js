/** @odoo-module **/

import { registry } from '@web/core/registry'
import { RelationalModel } from '@web/model/relational_model/relational_model'
import { AccordionArchParser } from './accordion_arch_parser'
import { AccordionCompiler } from './accordion_compiler'
import { AccordionController } from './accordion_controller'
import { AccordionRenderer } from './accordion_renderer'

export const accordionView = {
  type: 'accordion',

  display_name: 'Accordion',
  icon: 'oi oi-view-accordion',
  multiRecord: true,

  ArchParser: AccordionArchParser,
  Controller: AccordionController,
  Model: RelationalModel,
  Renderer: AccordionRenderer,
  Compiler: AccordionCompiler,

  buttonTemplate: 'web.AccordionView.Buttons',

  props: (genericProps, view) => {
    const { arch, relatedModels, resModel } = genericProps
    const { ArchParser } = view
    const archInfo = new ArchParser().parse(arch, relatedModels, resModel)
    const defaultGroupBy =
      genericProps.searchMenuTypes.includes('groupBy') &&
      archInfo.defaultGroupBy

    return {
      ...genericProps,
      // Compiler: view.Compiler, // don't pass it automatically in stable, for backward compat
      Model: view.Model,
      Renderer: view.Renderer,
      buttonTemplate: view.buttonTemplate,
      archInfo,
      defaultGroupBy,
    }
  },
}

registry.category('views').add('accordion', accordionView)
