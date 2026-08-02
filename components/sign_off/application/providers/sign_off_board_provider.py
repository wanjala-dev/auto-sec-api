"""Composition root — wires the sign-off board read port to its ORM adapter.

Providers are the sanctioned place to defer-import persistence-backed adapters
(architecture-manifesto Rule 9). The materializer asks this provider for the
:class:`SignOffBoardPort`; the wiring policy lives here, not in the service.
"""

from __future__ import annotations

from components.sign_off.application.ports.sign_off_board_port import SignOffBoardPort


def get_sign_off_board_port() -> SignOffBoardPort:
    from components.sign_off.infrastructure.adapters.orm_sign_off_board_repository import (
        OrmSignOffBoardRepository,
    )

    return OrmSignOffBoardRepository()
