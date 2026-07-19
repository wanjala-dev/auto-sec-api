"""Composition-root providers for the audit bounded context.

Controllers in other bounded contexts (campaigns, events, sponsorship)
MUST import audit functionality through these providers rather than
reaching into ``components.audit.infrastructure.*`` directly. The
architecture test ``test_controllers_do_not_import_concrete_adapters``
enforces this boundary.
"""

from __future__ import annotations
