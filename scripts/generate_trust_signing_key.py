"""Generate an Ed25519 keypair for GaiaLab Trust Receipt signing.

The private key is printed once. Store it in a secret manager or environment
variable; do not commit it to source control.
"""

from __future__ import annotations

import json

from src.receipt_signing import generate_signing_keypair


if __name__ == "__main__":
    print(json.dumps(generate_signing_keypair(), indent=2))
