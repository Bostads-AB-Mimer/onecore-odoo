# This is stupid: Odoo's test discovery requires explicit imports of test modules
# rather than just importing packages, so we need to import each test file here
from .models import test_maintenance
from .models import test_maintenance_building
from .models import test_maintenance_facility
from .models import test_maintenance_lease
from .models import test_maintenance_maintenance_unit
from .models import test_maintenance_parking_space
from .models import test_maintenance_property
from .models import test_maintenance_rental_property
from .models import test_maintenance_request_category
from .models import test_maintenance_team
from .models import test_maintenance_tenant
from .models.handlers import test_base_handler
from .models.handlers import test_handler_factory
from .models.services import test_maintenance_workflow_service
from .models.services import test_record_management_service
from .models.services import test_external_contractor_service
from .models.services import test_component_ai_analysis_service
from .models.services import test_component_hierarchy_service
from .models.services import test_component_onecore_service
from .security import test_basic_user
from .security import test_external_contractor
from .utils import test_component_utils
