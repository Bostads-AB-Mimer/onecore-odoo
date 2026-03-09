import logging
from .base_handler import BaseMaintenanceHandler

_logger = logging.getLogger(__name__)


class RentalObjectBaseHandler(BaseMaintenanceHandler):
    """Base handler for rental object searches (rental properties, parking spaces, facilities)."""

    def handle_search(self, search_type, search_value, space_caption):
        if search_type in ["pnr", "contactCode", "leaseId", "rentalObjectId"]:
            work_order_data = self.core_api.fetch_form_data(
                search_type, search_value, space_caption
            )

            if not work_order_data:
                _logger.info("No data found in response.")
                return self._return_no_results_warning(search_value)

            self.update_form_options(work_order_data)
            self._set_form_selections(search_type, search_value)
        else:
            raise ValueError(
                f"{self.__class__.__name__} does not support search type: {search_type}"
            )

    def _set_lease_and_tenant_selections(self, search_type, search_value):
        """Set lease and tenant form selections after a search."""
        lease_records = self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        if lease_records:
            active_lease = self._select_active_lease_option(lease_records)
            self.record.lease_option_id = active_lease.id

            tenant_records = self.env["maintenance.tenant.option"].search(
                [("user_id", "=", self.env.user.id),
                 ("lease_option_id", "=", active_lease.id)]
            )
            if tenant_records:
                self.record.tenant_option_id = self._select_tenant_for_search(
                    tenant_records, search_type, search_value
                ).id

    def _clear_lease_and_tenant_options(self):
        """Clear existing lease and tenant options when no lease data is available."""
        self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
        self.env["maintenance.tenant.option"].search(
            [("user_id", "=", self.env.user.id)]
        ).unlink()
