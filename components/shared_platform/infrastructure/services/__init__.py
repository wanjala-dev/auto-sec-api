# ``tenant_router`` used to be star-imported here. It defined a SECOND class
# named ``TenantRouter`` — the fork-inherited one — whose db_for_read/write
# returned ``get_current_db_name()``, a threading.local the live router never
# writes. It was never in ``DATABASE_ROUTERS`` (that names
# ``shared_platform.infrastructure.tenancy.router.TenantRouter``), so it routed
# nothing; but exporting a same-named router from a package `import *` is how
# the wrong one gets picked up. Deleted 2026-08-19.
from components.shared_platform.infrastructure.services.celery_tasks import *  # noqa: F403
from components.shared_platform.infrastructure.services.core_utils import *  # noqa: F403
from components.shared_platform.infrastructure.services.core_validators import *  # noqa: F403
from components.shared_platform.infrastructure.services.decorators import *  # noqa: F403
from components.shared_platform.infrastructure.services.feature_flags import *  # noqa: F403
from components.shared_platform.infrastructure.services.honeypot_forms import *  # noqa: F403
from components.shared_platform.infrastructure.services.openai_client import *  # noqa: F403
from components.shared_platform.infrastructure.services.tenant_utils import *  # noqa: F403
from components.shared_platform.infrastructure.services.upload_pagination import *  # noqa: F403
