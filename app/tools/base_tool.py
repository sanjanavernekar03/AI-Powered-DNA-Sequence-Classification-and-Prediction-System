import abc
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    """Standardized result returned by all tools."""
    success: bool
    data: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata
        }


class BaseTool(abc.ABC):
    """Abstract base class for all Agentic tools."""

    name: str = ""
    description: str = ""
    parameters_schema: Dict[str, Any] = {}

    @abc.abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given keyword arguments."""
        pass

    def get_definition(self) -> Dict[str, Any]:
        """Return tool metadata for agent discovery and prompting."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema
        }
