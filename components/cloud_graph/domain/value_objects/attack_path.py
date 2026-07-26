"""Value objects for attack-path correlation — the CNAPP toxic-combination signal."""

from __future__ import annotations

from enum import Enum


class AttackPathCategory(str, Enum):
    """The kind of toxic combination a path represents (ADR 0005 §6 attack-path queries).

    Categorised by the crown-jewel SINK the public entry reaches — that's what makes
    the combination toxic and drives the risk score.
    """

    PUBLIC_COMPUTE_ADMIN = "public_compute_admin"  # §6.1 public compute → powerful (admin) role
    PUBLIC_DATA_EXPOSURE = "public_data_exposure"  # §6.3 public compute → sensitive data store

    @property
    def label(self) -> str:
        return {
            AttackPathCategory.PUBLIC_COMPUTE_ADMIN: "Public compute with admin privileges",
            AttackPathCategory.PUBLIC_DATA_EXPOSURE: "Public compute reaching sensitive data",
        }[self]
