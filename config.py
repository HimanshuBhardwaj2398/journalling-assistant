"""
Legacy configuration module - maintained for backward compatibility.
New code should use: from config.settings import get_settings

This module re-exports commonly used configuration values.
"""

from config.settings import get_settings

# Get the settings instance
_settings = get_settings()

# Backward compatible exports
hf_token = _settings.hf_token
llamaparse_api = _settings.parsing.llamaparse_api_key
db_url = _settings.database.url
voyage_api_key = _settings.embedding.voyage_api_key

# Also export DATABASE_URL for compatibility with db/database.py
DATABASE_URL = _settings.database.url
