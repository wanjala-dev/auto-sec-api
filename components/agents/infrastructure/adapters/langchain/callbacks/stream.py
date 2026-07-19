"""
Streaming Callback Handler for LangChain
"""
from langchain.callbacks.base import BaseCallbackHandler
from queue import Queue
from typing import Any, Dict, List, Optional, Union
from langchain.schema import AgentAction, AgentFinish, LLMResult


class StreamingHandler(BaseCallbackHandler):
    """
    Custom callback handler for streaming LLM responses.
    """
    
    def __init__(self, queue: Queue):
        """
        Initialize the streaming handler.
        
        Args:
            queue: Queue to put streaming tokens into
        """
        self.queue = queue
        self.streaming_run_ids = set()
    
    def on_chat_model_start(
        self, 
        serialized: Dict[str, Any], 
        messages: List[List], 
        run_id: str, 
        **kwargs: Any
    ) -> None:
        """
        Called when a chat model starts running.
        
        Args:
            serialized: Serialized model configuration
            messages: List of message lists
            run_id: Unique run identifier
            **kwargs: Additional arguments
        """
        if serialized.get("kwargs", {}).get("streaming", False):
            self.streaming_run_ids.add(run_id)
    
    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """
        Called when a new token is generated.
        
        Args:
            token: The new token
            **kwargs: Additional arguments
        """
        self.queue.put(token)
    
    def on_llm_end(self, response: LLMResult, run_id: str, **kwargs: Any) -> None:
        """
        Called when LLM finishes running.
        
        Args:
            response: The LLM response
            run_id: Unique run identifier
            **kwargs: Additional arguments
        """
        if run_id in self.streaming_run_ids:
            self.queue.put(None)  # Signal end of stream
            self.streaming_run_ids.remove(run_id)
    
    def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> None:
        """
        Called when LLM encounters an error.
        
        Args:
            error: The error that occurred
            **kwargs: Additional arguments
        """
        self.queue.put(None)  # Signal end of stream on error
    
    def on_agent_action(self, action: AgentAction, **kwargs: Any) -> Any:
        """
        Called when agent takes an action.
        
        Args:
            action: The agent action
            **kwargs: Additional arguments
        """
        pass
    
    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """
        Called when agent finishes.
        
        Args:
            finish: The agent finish result
            **kwargs: Additional arguments
        """
        pass









































