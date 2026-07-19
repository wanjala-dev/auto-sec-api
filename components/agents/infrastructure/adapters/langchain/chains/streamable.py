"""
Streamable Chain Mixin for streaming responses
"""
from queue import Queue
from threading import Thread
from typing import Generator, Any, Dict, List, Optional
from ..callbacks.stream import StreamingHandler


class StreamableChain:
    """Mixin for making chains streamable"""
    
    def stream(self, input_data: Dict[str, Any], **kwargs) -> Generator[str, None, None]:
        """
        Stream the chain execution
        
        Args:
            input_data: Input data for the chain
            **kwargs: Additional arguments for the chain
        
        Yields:
            Tokens as they are generated
        """
        queue = Queue()
        handler = StreamingHandler(queue)
        
        # Add streaming handler to callbacks
        callbacks = kwargs.get('callbacks', [])
        callbacks.append(handler)
        kwargs['callbacks'] = callbacks
        
        def task():
            try:
                self(input_data, **kwargs)
            except Exception as e:
                queue.put(f"Error: {str(e)}")
            finally:
                # Always signal the end of the stream to avoid hanging consumers.
                queue.put(None)
        
        # Start chain execution in separate thread
        thread = Thread(target=task)
        thread.start()
        
        # Yield tokens as they come
        while True:
            token = queue.get()
            if token is None:
                break
            yield token
        
        thread.join()
    
    def stream_async(self, input_data: Dict[str, Any], **kwargs) -> Generator[str, None, None]:
        """
        Async version of stream (placeholder for future async implementation)
        
        Args:
            input_data: Input data for the chain
            **kwargs: Additional arguments for the chain
        
        Yields:
            Tokens as they are generated
        """
        # For now, just call the sync version
        # In the future, this could be implemented with asyncio
        yield from self.stream(input_data, **kwargs)
