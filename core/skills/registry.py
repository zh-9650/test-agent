from typing import Callable, Any
from core.skills.base import BaseSkill

class SkillRegistry:
    """Central registry for managing Agent Skills across different phases."""
    
    def __init__(self):
        self._skills: list[BaseSkill] = []
        
    def register(self, skill: BaseSkill) -> None:
        """Register a new skill into the registry."""
        self._skills.append(skill)
        
    def get_tools_for_phase(self, phase: str) -> list[Callable[..., Any]]:
        """Retrieve all @tool functions registered for the given phase."""
        tools = []
        for skill in self._skills:
            if phase in skill.supported_phases:
                tools.append(skill.get_tool())
        return tools

# Global Singleton Registry
skill_registry = SkillRegistry()

def init_registry() -> None:
    """Initialize the registry with default skills.
    This can be called during application startup to populate the registry.
    """
    # For now, we will dynamically inject the legacy tools into the registry 
    # during graph creation until they are fully refactored into BaseSkill objects.
    pass
