"""External contractor specific business logic."""

from odoo import _, exceptions

from .maintenance_workflow_service import MaintenanceStageManager


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
        blocked = record.stage_id & self.restricted_stages()
        if blocked:
            raise exceptions.UserError(
                f"Du har inte behörighet att flytta detta ärende från {blocked[:1].name}"
            )

        # Cannot move TO Avslutad
        if new_stage_id in MaintenanceStageManager(self.env).closed_stage().ids:
            raise exceptions.UserError(
                "Du har inte behörighet att flytta detta ärende till Avslutad"
            )

    def restricted_stages(self):
        """Utförd, Avslutad and Återsänd: stages in which external contractors
        can no longer change a record."""
        return MaintenanceStageManager(self.env).restricted_stages()

    def get_restricted_status(self, record):
        """Check if record is in a restricted state for external contractors."""
        if not self.is_external_contractor():
            return False

        return record.stage_id in self.restricted_stages()
    
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