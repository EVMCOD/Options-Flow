"""
ProviderCredentials: safe wrapper around provider credential dicts.

Rationale
---------
Credentials (API keys, tokens, passwords) must never appear in:
  - log output (structlog event dicts, tracebacks)
  - repr() of provider objects
  - Python's default str() on dicts

This wrapper enforces that at the boundary where credentials leave the DB
and enter the provider. It also provides a single place to add
encryption/decryption when a secret manager (Vault, AWS SSM, GCP Secret
Manager) is introduced.

Migration path to encrypted credentials
----------------------------------------
When adding at-rest encryption:
  1. Add an `_decrypt(data: dict) -> dict` function here that calls the
     secret manager or derives an AEAD key from a KMS-managed master key.
  2. Change `__init__` to call `_decrypt(data)` before storing `_data`.
  3. The rest of the codebase is unaffected — providers access credentials
     only through this class.

Nothing else needs to change.
"""

from __future__ import annotations

from typing import Any


class ProviderCredentials:
    """
    Opaque wrapper around a credentials dictionary.

    Usage in provider classes:
        api_key = self.credentials.require("api_key")
        host    = self.credentials.get("host", "127.0.0.1")
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        # Future: self._data = _decrypt(data)
        self._data: dict = data

    # ------------------------------------------------------------------
    # Public accessor interface
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for key, or default if not present."""
        return self._data.get(key, default)

    def require(self, key: str) -> str:
        """
        Return the value for key, raising a clear error if absent or empty.

        Prefer this over .get() for required credentials so providers fail
        loudly at initialisation time rather than silently during fetch.
        """
        value = self._data.get(key)
        if not value:
            raise ValueError(
                f"Required credential '{key}' is missing or empty in the "
                f"provider configuration. "
                f"Update via: PATCH /api/v1/tenants/{{tenant_id}}/providers/{{config_id}}"
            )
        return str(value)

    def has(self, key: str) -> bool:
        return bool(self._data.get(key))

    # ------------------------------------------------------------------
    # Safety: never expose credential values in repr/str/log output
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        keys = list(self._data.keys())
        return f"ProviderCredentials(keys={keys})"

    def __str__(self) -> str:
        return self.__repr__()

    def __format__(self, format_spec: str) -> str:
        return self.__repr__()
