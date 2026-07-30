"""v2 原始资料接入。"""

from .artifact_store import FilesystemArtifactStore
from .inspection import inspect_source

__all__ = ["FilesystemArtifactStore", "inspect_source"]
