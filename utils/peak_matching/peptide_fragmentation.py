"""Backward-compatibility shim.

All functionality has been moved to sub-modules:
  - constants.py     : mass constants, amino acid data, ion colors
  - fragmentation.py : fragment ion generation, neutral losses, filtering
  - matching.py      : peak matching, cached fragmentation+match pipeline

This file re-exports every public name so existing imports continue to work.
"""
from .constants import *          # noqa: F401,F403
from .fragmentation import *      # noqa: F401,F403
from .matching import *           # noqa: F401,F403
