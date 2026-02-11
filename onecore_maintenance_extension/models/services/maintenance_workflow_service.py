"""Service for managing maintenance request workflow, stages and field changes."""

from odoo import _, exceptions, fields
from markupsafe import Markup


class MaintenanceStageManager:
    """Service for managing maintenance request workflow and stage transitions."""

    def __init__(self, env):
        self.env = env

    def handle_stage_change(self, record, new_stage_id):
        """Handle all logic when stage changes."""
        # Handle resource assignment workflow
        if not record.user_id:
            self._validate_unassigned_resource(new_stage_id)

    def handle_resource_assignment(self, record, new_user_id):
        """Handle workflow when user is assigned/unassigned."""
        if new_user_id and record.stage_id.name == "Väntar på handläggning":
            # Auto-transition to "Resurs tilldelad" when user is assigned
            resource_allocated_stage = self._get_stage_by_name("Resurs tilldelad")
            if resource_allocated_stage:
                return {"stage_id": resource_allocated_stage.id}

        elif new_user_id is False and record.stage_id.name == "Resurs tilldelad":
            # Auto-transition back to "Väntar på handläggning" when user is unassigned
            initial_stage = self._get_stage_by_name("Väntar på handläggning")
            if initial_stage:
                return {"stage_id": initial_stage.id}

        return {}

    def _validate_unassigned_resource(self, new_stage_id):
        """Validate stage change when no resource is assigned."""
        allowed_stages = self.env["maintenance.stage"].search(
            [("name", "in", ["Väntar på handläggning", "Avslutad"])]
        )
        if new_stage_id not in allowed_stages.ids:
            raise exceptions.UserError(
                "Ingen resurs är tilldelad. Vänligen välj en resurs."
            )

    def handle_initial_user_assignment(self, request):
        """Handle stage transition when user is assigned during request creation."""
        if request.user_id and request.stage_id.name == "Väntar på handläggning":
            resource_allocated_stage = self._get_stage_by_name("Resurs tilldelad")
            if resource_allocated_stage:
                request.stage_id = resource_allocated_stage.id

    def _get_stage_by_name(self, stage_name):
        """Get stage record by name."""
        return self.env["maintenance.stage"].search(
            [("name", "=", stage_name)], limit=1
        )


class FieldChangeTracker:
    """Service for tracking and formatting field changes in maintenance requests."""

    SKIP_FIELDS = {
        "message_main_attachment_id",
        "message_ids",
        "activity_ids",
        "website_message_ids",
        "__last_update",
        "display_name",
        "stage_id",
        "has_loan_product",      # Custom logging in write()
        "loan_product_details",  # Custom logging in write()
    }

    def __init__(self, env):
        self.env = env

    def track_field_changes(self, records, vals):
        """Track changes to fields and return formatted change descriptions."""
        filtered_vals = {k: v for k, v in vals.items() if k not in self.SKIP_FIELDS}

        if not filtered_vals:
            return {}

        changes_by_record = {}
        for record in records:
            changes = []
            for field, new_value in filtered_vals.items():
                old_value = record[field]
                field_obj = record._fields[field]

                if self._should_skip_field_change(field_obj, old_value, new_value):
                    continue

                field_label = field_obj.get_description(self.env)["string"]
                change_text = self._format_field_change(
                    field_obj, old_value, new_value, field_label
                )
                if change_text:
                    changes.append(change_text)

            changes_by_record[record.id] = changes

        return changes_by_record

    def post_change_notifications(self, records, changes_by_record):
        """Post change notifications to the records."""
        for record in records:
            if record.id in changes_by_record and changes_by_record[record.id]:
                html_content = (
                    "<div>" + "<br/>".join(changes_by_record[record.id]) + "</div>"
                )
                record.message_post(
                    body=Markup(html_content),
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )

    def _should_skip_field_change(self, field_obj, old_value, new_value):
        """Check if field change should be skipped."""
        if isinstance(field_obj, fields.Many2one):
            old_id = old_value.id if old_value else False
            new_id = new_value if isinstance(new_value, (int, bool)) else (new_value.id if new_value else False)
            return old_id == new_id
        else:
            return old_value == new_value

    def _format_field_change(self, field_obj, old_value, new_value, field_label):
        """Format a field change for display."""
        if field_obj.name == "description":
            return f"<strong>{field_label}:</strong> Uppdaterad"

        if isinstance(field_obj, fields.Many2one):
            return self._format_many2one_change(field_obj, old_value, new_value, field_label)
        elif isinstance(field_obj, fields.Selection):
            return self._format_selection_change(field_obj, old_value, new_value, field_label)
        elif isinstance(field_obj, fields.Boolean):
            return self._format_boolean_change(old_value, new_value, field_label)
        elif isinstance(field_obj, (fields.Date, fields.Datetime)):
            return self._format_date_change(old_value, new_value, field_label)
        else:
            return self._format_generic_change(old_value, new_value, field_label)

    def _format_many2one_change(self, field_obj, old_value, new_value, field_label):
        """Format Many2one field change."""
        old_display = old_value.display_name if old_value else "Inte valt"
        if new_value:
            new_record = self.env[field_obj.comodel_name].browse(new_value)
            new_display = (
                new_record.display_name if new_record.exists() else "Inte valt"
            )
        else:
            new_display = "Inte valt"

        return (
            f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"
            if old_display != new_display
            else None
        )

    def _format_selection_change(self, field_obj, old_value, new_value, field_label):
        """Format Selection field change."""
        selection = field_obj.selection
        if callable(selection):
            selection = selection(self.env)

        old_display = next(
            (label for value, label in selection if value == old_value),
            "Inte satt" if old_value in [False, None, ""] else str(old_value),
        )
        new_display = next(
            (label for value, label in selection if value == new_value),
            "Inte satt" if new_value in [False, None, ""] else str(new_value),
        )

        return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

    def _format_boolean_change(self, old_value, new_value, field_label):
        """Format Boolean field change."""
        old_display = "Ja" if old_value else "Nej"
        new_display = "Ja" if new_value else "Nej"
        return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

    def _format_date_change(self, old_value, new_value, field_label):
        """Format Date/Datetime field change."""
        old_display = old_value.strftime("%Y-%m-%d") if old_value else "Inte satt"

        if isinstance(new_value, str):
            try:
                new_date = (
                    fields.Date.from_string(new_value)
                    if new_value != "False"
                    else None
                )
                new_display = (
                    new_date.strftime("%Y-%m-%d") if new_date else "Inte satt"
                )
            except:
                new_display = str(new_value) if new_value else "Inte satt"
        else:
            new_display = (
                new_value.strftime("%Y-%m-%d") if new_value else "Inte satt"
            )

        return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"

    def _format_generic_change(self, old_value, new_value, field_label):
        """Format generic field change."""
        old_display = str(old_value) if old_value else "Inte satt"
        new_display = str(new_value) if new_value else "Inte satt"
        return f"<strong>{field_label}:</strong> <span style='color: #999; text-decoration: line-through;'>{old_display}</span> → {new_display}"