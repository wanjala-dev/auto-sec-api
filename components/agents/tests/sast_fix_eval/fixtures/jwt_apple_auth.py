"""Frozen corpus source — the Class B shape behind finding 9975 (#867/#870).

The correct fix is NOT a line edit: verifying Apple's identity token requires
fetching Apple's public keys from their JWKS endpoint and selecting by ``kid``
— new code, new dependency on their key service, error handling. The key is
deliberately not in this repository.
"""

import jwt


def verify_apple_identity_token(id_token: str) -> dict:
    claims = jwt.decode(id_token, options={"verify_signature": False})
    if claims.get("iss") != "https://appleid.apple.com":
        raise ValueError("unexpected issuer")
    return claims
