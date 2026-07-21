import os

from celery import Celery

import infrastructure.celery.signals
from infrastructure.celery.database_safe_task import DatabaseSafeTask

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings.local")

app = Celery("api")

app.Task = DatabaseSafeTask

# Using a string here means the worker doesn't have to serialize
# the configuration object to recipient processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a CELERY_ prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# DDD components live outside the Django app tree, so explicit imports are
# required for `tasks.py` modules inside `components/`. Add new task modules
# here as we ship them. (F401/E402 are per-file-ignored — these are
# intentional side-effect imports that register Celery tasks.)
# NOTE: agent_tasks (run_ai_teammate_cycle + schedule_ai_teammate_runs) imports
# ORM models at module level, so it CANNOT be eager-imported here — celery.py
# runs at api/__init__ time, before the Django app registry is ready. It is
# registered lazily in AgentsCLIConfig.ready() instead (same pattern as the
# workflow tasks).
import components.agents.infrastructure.tasks.ai_action_rollup_tasks
import components.agents.infrastructure.tasks.ai_quality_rollup_tasks
import components.agents.infrastructure.tasks.eval_tasks
import components.identity.workers.tasks
import components.knowledge.infrastructure.tasks.index_freshness_tasks
import components.knowledge.infrastructure.tasks.workspace_index_tasks
import components.notifications.workers.tasks
import components.payments.workers.tasks
import components.project.infrastructure.tasks.at_risk_detector_tasks
import components.recycle_bin.workers.tasks
import components.shared_platform.infrastructure.tasks.document_import_tasks
import components.shared_platform.workers.tasks
import components.sign_off.workers.tasks
import components.subscription.workers.tasks

# NOTE: workflow tasks are registered via the autodiscover shim at
# infrastructure/persistence/workspaces/workflows/tasks.py (that app IS in
# INSTALLED_APPS). They can't be eager-imported here — workflow_tasks imports
# ORM models at module level and api/celery.py runs before the app registry is
# ready (AppRegistryNotReady).
