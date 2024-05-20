/** @odoo-module **/
import { Component } from '@odoo/owl';
import { View } from '@web/views/view';
import { Field } from '@web/views/fields/field';
import { Record } from '@web/model/record';
import { ViewScaleSelector } from '@web/views/view_components/view_scale_selector';
export class MobileRenderer extends Component {
  async setup() {}
}
MobileRenderer.template = 'onecore_ui.MobileRenderer';
MobileRenderer.components = {
  View,
  Field,
  Record,
  ViewScaleSelector,
};
