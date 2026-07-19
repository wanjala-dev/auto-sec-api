"""Audit bounded context — append-only field-level history for tracked entities.

Exposes a ``log_field_change`` write helper and a ``get_entity_history``
read helper via ``infrastructure.services.audit_log``. Other contexts
(campaigns, events, sponsorship) call these helpers from their PATCH
handlers to record goal edits and other mutations.

See ``infrastructure/persistence/audit/models.py::EntityAuditLog`` for
the ORM model.
"""
