"""External contractor specific business logic."""

from odoo import _, exceptions


class ExternalContractorService:
    """Service handling all external contractor-specific business logic."""
    
    def __init__(self, env):
        self.env = env
        self.user = env.user
    
    def is_external_contractor(self):
        """Check if current user is an external contractor."""
        return self.user.has_group(
            "onecore_maintenance_extension.group_external_contractor"
        )
    
    def validate_stage_transition(self, record, new_stage_id):
        """Validate if external contractor can transition to new stage."""
        if not self.is_external_contractor():
            return  # Not applicable
        
        # Cannot move FROM these stages
        if record.stage_id.name == "Utförd":
            raise exceptions.UserError(
                "Du har inte behörighet att flytta detta ärende från Utförd"
            )
        if record.stage_id.name == "Avslutad":
            raise exceptions.UserError(
                "Du har inte behörighet att flytta detta ärende från Avslutad"
            )

        # Cannot move TO restricted stages
        restricted_stages = self.env["maintenance.stage"].search(
            [("name", "=", "Avslutad")]
        )
        if new_stage_id in restricted_stages.ids:
            raise exceptions.UserError(
                "Du har inte behörighet att flytta detta ärende till Avslutad"
            )
    
    def get_restricted_status(self, record):
        """Check if record is in a restricted state for external contractors."""
        if not self.is_external_contractor():
            return False
            
        restricted_stage_ids = self.env["maintenance.stage"].search(
            [("name", "in", ["Utförd", "Avslutad"])]
        )
        return record.stage_id in restricted_stage_ids
    
    def can_access_record(self, record):
        """Check if external contractor can access this record."""
        if not self.is_external_contractor():
            return True  # Not applicable
            
        # Add any external contractor specific access rules here
        return True
    
    def get_allowed_actions(self, record):
        """Get list of actions allowed for external contractors on this record."""
        if not self.is_external_contractor():
            return None  # Not applicable
        
        actions = []
        if not self.get_restricted_status(record):
            actions.extend(['edit', 'comment', 'attach_files'])
        else:
            actions.extend(['view', 'comment'])  # Limited actions for restricted records
            
        return actions