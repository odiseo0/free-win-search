from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.settings.api_settings import api_settings
    from src.settings.cache_settings import cache_settings
    from src.settings.db_settings import db_settings

__all__ = ["api_settings", "cache_settings", "db_settings"]


def __getattr__(name: str) -> Any:
    if name == "api_settings":
        from src.settings.api_settings import api_settings

        return api_settings

    if name == "cache_settings":
        from src.settings.cache_settings import cache_settings

        return cache_settings

    if name == "db_settings":
        from src.settings.db_settings import db_settings

        return db_settings

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
