# Shim for one release — EngineSkeleton is now the real Engine.
# Remove in M4. Tests still import EngineSkeleton by name.
from .engine import Engine as EngineSkeleton

__all__ = ["EngineSkeleton"]
