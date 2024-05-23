/** @odoo-module **/
import { Component } from '@odoo/owl'
import { View } from '@web/views/view'
import { Field } from '@web/views/fields/field'
import { Record } from '@web/model/record'
import { ViewScaleSelector } from '@web/views/view_components/view_scale_selector'
import { accordionView } from '@onecore_ui/accordion/accordion_view'
import { AccordionArchParser } from '@onecore_ui/accordion/accordion_arch_parser'
import { AccordionCompiler } from '@onecore_ui/accordion/accordion_compiler'
import { AccordionController } from '@onecore_ui/accordion/accordion_controller'
import { AccordionRenderer } from '@onecore_ui/accordion/accordion_renderer'

export class MobileRenderer extends Component {
  async setup() {}
}
MobileRenderer.template = 'onecore_ui.MobileRenderer'
MobileRenderer.components = {
  View,
  Field,
  Record,
  ViewScaleSelector,
  AccordionRenderer,
  AccordionArchParser,
  accordionView,
  AccordionCompiler,
  AccordionController,
}
