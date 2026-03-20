"""
Provider registry: maps provider_type strings to provider classes.

Usage
-----
# Register a provider (done at module load in each provider file):
@ProviderRegistry.register("polygon")
class PolygonOptionsDataProvider(BaseOptionsDataProvider):
    ...

# Resolve a provider from a TenantProviderConfig record:
provider = ProviderRegistry.resolve(config)

Design notes
------------
- Registration is done via decorator at import time in each provider module.
- The registry is populated in _bootstrap() called from this module's bottom.
- Adding a new provider requires only: (1) write the class, (2) add its
  import to _bootstrap(), (3) POST to /tenants/{id}/providers with the
  new provider_type. No other code changes needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Type

from app.core.logging_setup import get_logger
from app.providers.base import BaseOptionsDataProvider

if TYPE_CHECKING:
    from app.tenants.models import TenantProviderConfig

log = get_logger(__name__)


class ProviderRegistry:
    _registry: dict[str, Type[BaseOptionsDataProvider]] = {}

    @classmethod
    def register(cls, provider_type: str):
        """
        Decorator that registers a provider class under a string key.

        Example:
            @ProviderRegistry.register("polygon")
            class PolygonProvider(BaseOptionsDataProvider):
                ...
        """
        def decorator(klass: Type[BaseOptionsDataProvider]) -> Type[BaseOptionsDataProvider]:
            if provider_type in cls._registry:
                log.warning(
                    "provider_registry.overwriting",
                    provider_type=provider_type,
                    previous=cls._registry[provider_type].__name__,
                    new=klass.__name__,
                )
            cls._registry[provider_type] = klass
            log.debug("provider_registry.registered", provider_type=provider_type, class_name=klass.__name__)
            return klass
        return decorator

    @classmethod
    def resolve(cls, config: "TenantProviderConfig") -> BaseOptionsDataProvider:
        """
        Instantiate the provider for a given TenantProviderConfig.

        The provider class receives:
          - credentials: dict (auth material — keys/tokens)
          - config:      dict (operational settings — timeouts, sandboxes, etc.)
        """
        klass = cls._registry.get(config.provider_type)
        if klass is None:
            available = list(cls._registry.keys())
            raise ValueError(
                f"Provider type '{config.provider_type}' is not registered. "
                f"Available providers: {available}"
            )
        return klass(
            credentials=config.credentials_json or {},
            config=config.config_json or {},
        )

    @classmethod
    def is_registered(cls, provider_type: str) -> bool:
        return provider_type in cls._registry

    @classmethod
    def registered_types(cls) -> List[str]:
        return list(cls._registry.keys())


def _bootstrap() -> None:
    """
    Import all provider modules and register them.

    Providers do NOT import this registry module (avoids circular imports).
    Registration is done here explicitly after each import.

    To add a new provider:
      1. Implement the class in app/providers/<name>.py
      2. Add its import + registration line below.
    """
    from app.providers.mock import MockOptionsDataProvider
    ProviderRegistry._registry["mock"] = MockOptionsDataProvider

    from app.providers.polygon import PolygonOptionsDataProvider
    ProviderRegistry._registry["polygon"] = PolygonOptionsDataProvider

    from app.providers.ibkr_delayed import IBKRDelayedProvider
    ProviderRegistry._registry["ibkr_delayed"] = IBKRDelayedProvider

    # Future providers:
    # from app.providers.tradier import TradierOptionsDataProvider
    # ProviderRegistry._registry["tradier"] = TradierOptionsDataProvider
    #
    # from app.providers.thetadata import ThetaDataOptionsProvider
    # ProviderRegistry._registry["thetadata"] = ThetaDataOptionsProvider
    #
    # from app.providers.tradier import TradierOptionsDataProvider
    # ProviderRegistry._registry["tradier"] = TradierOptionsDataProvider
    #
    # from app.providers.thetadata import ThetaDataOptionsProvider
    # ProviderRegistry._registry["thetadata"] = ThetaDataOptionsProvider


_bootstrap()
