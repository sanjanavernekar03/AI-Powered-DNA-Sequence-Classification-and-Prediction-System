import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from app.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class AgentStep:
    """Represents a single thinking/tool execution step taken by an agent."""
    step_number: int
    thought: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[ToolResult] = None


@dataclass
class AgentResponse:
    """Final answer and execution trace returned by an agent."""
    response: str
    steps: List[AgentStep] = field(default_factory=list)
    tools_called: List[str] = field(default_factory=list)
    final_data: Optional[Dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response": self.response,
            "tools_called": self.tools_called,
            "final_data": self.final_data,
            "success": self.success,
            "error": self.error,
            "steps": [
                {
                    "step": s.step_number,
                    "thought": s.thought,
                    "tool": s.tool_name,
                    "input": s.tool_input,
                    "output": s.tool_output.to_dict() if s.tool_output else None
                }
                for s in self.steps
            ]
        }


class BaseAgent(abc.ABC):
    """Abstract base class for all autonomous reasoning agents."""

    def __init__(self, tools: Optional[List[BaseTool]] = None, max_iterations: int = 5):
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.max_iterations = max_iterations

    def register_tool(self, tool: BaseTool):
        """Add a tool to the agent's available inventory."""
        self.tools[tool.name] = tool

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return formatted metadata for all registered tools."""
        return [t.get_definition() for t in self.tools.values()]

    @abc.abstractmethod
    def run(self, user_query: str, **kwargs) -> AgentResponse:
        """Run multi-step reasoning and tool execution loop."""
        pass
