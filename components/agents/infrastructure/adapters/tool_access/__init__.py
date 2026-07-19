"""Tool access strategy adapters.

Each adapter implements ``ToolAccessPort`` for a specific access strategy:

- ``OrmToolAccessAdapter``  — Django ORM queries
- ``McpToolAccessAdapter``  — Model Context Protocol servers
- ``WebToolAccessAdapter``  — HTTP/REST API calls
- ``FileToolAccessAdapter`` — Local filesystem reads/writes
"""
