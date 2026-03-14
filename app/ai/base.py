"""
AI组件抽象基类
定义Agent、Tool、Workflow的标准接口契约
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolResult:
    """Tool执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent执行结果"""
    success: bool
    output: Any = None
    error: Optional[str] = None
    steps: list[str] = field(default_factory=list)


@dataclass
class WorkflowResult:
    """Workflow执行结果"""
    success: bool
    result: Any = None
    error: Optional[str] = None
    stage_results: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """
    AI工具基类

    Tool是原子化AI能力单元，遵循单一职责原则。
    每个Tool只做一件事，可独立测试和复用。
    """

    name: str
    description: str

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具逻辑"""
        ...

    def __repr__(self) -> str:
        return f"Tool({self.name})"


class BaseAgent(ABC):
    """
    AI Agent基类

    Agent通过组合多个Tool完成复杂任务。
    Agent只能通过Tool与外部系统交互，不直接操作数据库。
    """

    name: str
    description: str
    tools: list[BaseTool]

    @abstractmethod
    async def run(self, input_data: Any) -> AgentResult:
        """执行Agent任务"""
        ...

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """按名称获取Tool"""
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None

    def __repr__(self) -> str:
        return f"Agent({self.name}, tools={[t.name for t in self.tools]})"


class BaseWorkflow(ABC):
    """
    Workflow基类

    Workflow编排Agent和Tool的执行顺序，管理数据在步骤间的流转。
    """

    name: str
    description: str

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> WorkflowResult:
        """执行工作流"""
        ...

    def __repr__(self) -> str:
        return f"Workflow({self.name})"
