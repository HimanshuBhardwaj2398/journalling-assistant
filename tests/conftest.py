"""Test configuration.

Mocks out heavy/broken transitive dependencies so tests can import
ingestion.chunking without pulling in llama_cloud_services or llama_index.
"""

import sys
from unittest.mock import MagicMock

# Mock the problematic import chain:
# ingestion.__init__ → parsing → llama_cloud_services → llama_index → banks → griffe
# griffe 2.0.0 removed Docstring, breaking the chain.
_MOCKED_MODULES = [
    "llama_cloud_services",
    "llama_cloud_services.parse",
    "llama_cloud_services.parse.base",
    "llama_parse",
    "banks",
    "banks.config",
    "banks.utils",
]

for mod in _MOCKED_MODULES:
    sys.modules.setdefault(mod, MagicMock())
