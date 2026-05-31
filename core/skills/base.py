from abc import ABC, abstractmethod
from typing import Callable, Any

class BaseSkill(ABC):
    """Base class for all Agent Skills in the Smart Test Agent.
    
    Skills are modular capabilities that can be dynamically bound to the LLM
    based on the current execution phase.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the skill."""
        pass
        
    @property
    @abstractmethod
    def supported_phases(self) -> list[str]:
        """List of phases where this skill is available.
        Valid phases: 'exploration', 'planning', 'execution', 'reflection'.
        """
        pass
        
    @abstractmethod
    def get_tool(self) -> Callable[..., Any]:
        """Return the @tool decorated function that the LLM will call."""
        pass
