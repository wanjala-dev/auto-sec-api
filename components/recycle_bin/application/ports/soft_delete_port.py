from __future__ import annotations

from abc import ABC, abstractmethod


class SoftDeletePort(ABC):
    """Adapter that knows how to soft-delete / restore / purge one
    entity type. Implementations receive ``entity_id`` as a string so
    the bin can hold entries for entities with either UUID or integer
    primary keys — the adapter converts to the model's native PK type
    when it touches the ORM.
    """

    @abstractmethod
    def soft_delete(self, entity_id: str) -> dict: ...

    @abstractmethod
    def restore(self, entity_id: str) -> None: ...

    @abstractmethod
    def hard_delete(self, entity_id: str) -> None: ...

    @abstractmethod
    def entity_type(self) -> str: ...
