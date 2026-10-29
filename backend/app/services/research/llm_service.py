from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import get_settings
from app.services.observability import langchain_config
from typing import Iterator, Dict, Any
import logging

logger = logging.getLogger(__name__)


def _text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
            if isinstance(block, str) or (isinstance(block, dict) and not block.get("thought")
                                         and block.get("type") == "text")
        )
    return ""


class LLMService:
    def __init__(self):
        self.settings = get_settings()
        self.client = ChatGoogleGenerativeAI(
            model=self.settings.llm_model,
            google_api_key=self.settings.google_api_key,
            temperature=self.settings.temperature,
            top_p=self.settings.top_p,
            max_output_tokens=self.settings.max_tokens,
        )
    
    def invoke(self, messages: list) -> Dict[str, Any]:
        """Non-streaming invocation"""
        try:
            response = self.client.invoke(messages, config=langchain_config())
            result = {
                "content": _text_content(response.content),
                "reasoning": None
            }
            
            # Extract reasoning if available
            if hasattr(response, 'additional_kwargs') and response.additional_kwargs:
                if "reasoning_content" in response.additional_kwargs:
                    result["reasoning"] = response.additional_kwargs["reasoning_content"]
            
            return result
        except Exception as e:
            logger.error(f"LLM invocation error: {e}")
            raise
    
    def stream(self, messages: list) -> Iterator[Dict[str, str]]:
        """Streaming invocation"""
        try:
            for chunk in self.client.stream(messages, config=langchain_config()):
                # Check for reasoning content
                if chunk.additional_kwargs and "reasoning_content" in chunk.additional_kwargs:
                    yield {
                        "type": "reasoning",
                        "data": chunk.additional_kwargs["reasoning_content"]
                    }
                
                # Yield regular content
                content = _text_content(chunk.content)
                if content:
                    yield {
                        "type": "content",
                        "data": content
                    }
        except Exception as e:
            logger.error(f"LLM streaming error: {e}")
            raise


# Singleton instance
_llm_service = None

def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
