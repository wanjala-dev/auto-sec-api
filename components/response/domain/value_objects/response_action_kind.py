"""ResponseActionKind — the catalogue of reversible SOC response actions.

Deliberately small: slice 1 ships the one action the attack-path / cloud-exposure
findings actually motivate — revoking a public security-group ingress rule — plus
its inverse (re-authorize), which is the *same* mutation run backwards so rollback
reuses one code path. New kinds (disable IAM key, quarantine instance) are added
here + a branch in the cloud response adapter; the propose→approve→execute→rollback
lifecycle around them does not change.
"""

from __future__ import annotations

from enum import Enum


class ResponseActionKind(str, Enum):
    #: Remove a public inbound rule from a security group (the exposure fix).
    REVOKE_SG_INGRESS = "revoke_sg_ingress"
    #: Re-add a previously-revoked inbound rule — the exact inverse of a revoke.
    AUTHORIZE_SG_INGRESS = "authorize_sg_ingress"

    @property
    def inverse_kind(self) -> ResponseActionKind:
        return {
            ResponseActionKind.REVOKE_SG_INGRESS: ResponseActionKind.AUTHORIZE_SG_INGRESS,
            ResponseActionKind.AUTHORIZE_SG_INGRESS: ResponseActionKind.REVOKE_SG_INGRESS,
        }[self]
