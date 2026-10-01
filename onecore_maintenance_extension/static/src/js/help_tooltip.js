/** @odoo-module */
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component } from "@odoo/owl";

/**
 * The superscript "?" with the black help popover that form fields get from
 * their help text, for places that are not a field — e.g. a heading on a
 * kanban card:
 *
 *      <widget name="mimer_help_tooltip" text="What this block counts."/>
 *
 * Line breaks in the text (&#10; in the arch) are kept.
 *
 * A widget because view archs may not set data-tooltip themselves (Odoo
 * rejects the attribute at validation); the template sets it instead.
 */
export class HelpTooltip extends Component {
  static template = "onecore_maintenance_extension.HelpTooltip";
  static props = {
    ...standardWidgetProps,
    text: { type: String },
  };

  get tooltipInfo() {
    return JSON.stringify({ debug: false, field: { help: this.props.text } });
  }
}

registry.category("view_widgets").add("mimer_help_tooltip", {
  component: HelpTooltip,
  extractProps: ({ attrs }) => ({ text: attrs.text }),
});
