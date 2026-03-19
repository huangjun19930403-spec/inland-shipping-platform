"""LLM Provider 抽象接口
定义所有 LLM Provider 必须实现的统一协议。
"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMCallResult:
    """单次 LLM 调用的完整返回结果"""
    content: str           # 模型原始输出文本
    input_tokens: int      # 输入 token 数
    output_tokens: int     # 输出 token 数
    model: str             # 实际使用的模型 ID
    provider: str          # provider 标识（anthropic / openai / deepseek / tongyi）
    latency_ms: int        # 端到端耗时（毫秒）


class AbstractLLMProvider(ABC):
    """LLM Provider 统一接口

    所有 Provider 实现必须继承此类，保证调用方式一致。
    """
    provider_name: str

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMCallResult:
        """执行 LLM 补全

        Args:
            system_prompt: 系统提示词
            user_message:  用户消息
            model:         模型 ID（由调用方从配置传入）
            max_tokens:    最大输出 token 数
            temperature:   温度（0=确定性，1=创造性）

        Returns:
            LLMCallResult（含内容、token 计数、耗时）

        Raises:
            AIServiceError: 所有 API 层错误统一转换为此异常
        """
        ...

    def __repr__(self) -> str:
        return f"Provider({self.provider_name})"
