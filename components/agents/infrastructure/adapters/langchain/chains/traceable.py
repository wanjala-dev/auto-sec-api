"""Traceable Chain Mixin for tracing and monitoring."""

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TraceableChain:
    """Mixin for making chains traceable"""
    
    def __init__(self, *args, **kwargs):
        # Consume tracing-only kwargs so parent classes that don't accept
        # arbitrary kwargs (or any kwargs at all) still initialize correctly.
        self.metadata = kwargs.pop('metadata', {}) or {}
        self.trace_id = kwargs.pop('trace_id', str(uuid.uuid4()))
        super().__init__(*args, **kwargs)
        self.start_time = None
        self.end_time = None
    
    def __call__(self, *args, **kwargs):
        """
        Execute the chain with tracing
        
        Args:
            *args: Arguments for the chain
            **kwargs: Keyword arguments for the chain
        
        Returns:
            Chain execution result
        """
        self.start_time = time.time()
        
        # Add trace metadata to callbacks if available
        callbacks = kwargs.get('callbacks', [])
        
        # Create trace handler if tracing is enabled
        if self.metadata.get('enable_tracing', True):
            trace_handler = self._create_trace_handler()
            if trace_handler:
                callbacks.append(trace_handler)
        
        kwargs['callbacks'] = callbacks
        
        try:
            result = super().__call__(*args, **kwargs)
            self.end_time = time.time()
            self._log_trace_success(result)
            return result
        except Exception as e:
            self.end_time = time.time()
            self._log_trace_error(e)
            raise
    
    def _create_trace_handler(self):
        """Create a trace handler for monitoring"""
        # This is a placeholder for future tracing implementation
        # Could integrate with Langfuse, Weights & Biases, or other tools
        return None
    
    def _log_trace_success(self, result):
        """Log successful trace"""
        duration = self.end_time - self.start_time if self.start_time and self.end_time else 0
        
        trace_data = {
            'trace_id': self.trace_id,
            'status': 'success',
            'duration': duration,
            'timestamp': datetime.now().isoformat(),
            'metadata': self.metadata,
            'result_type': type(result).__name__
        }
        
        logger.info("ai.chain.trace.success", extra={"trace": trace_data})
    
    def _log_trace_error(self, error):
        """Log error trace"""
        duration = self.end_time - self.start_time if self.start_time and self.end_time else 0
        
        trace_data = {
            'trace_id': self.trace_id,
            'status': 'error',
            'duration': duration,
            'timestamp': datetime.now().isoformat(),
            'metadata': self.metadata,
            'error': str(error),
            'error_type': type(error).__name__
        }
        
        logger.exception("ai.chain.trace.error", extra={"trace": trace_data})
    
    def set_metadata(self, metadata: Dict[str, Any]):
        """Set trace metadata"""
        self.metadata.update(metadata)
    
    def get_trace_info(self):
        """Get current trace information"""
        return {
            'trace_id': self.trace_id,
            'metadata': self.metadata,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': (self.end_time - self.start_time) if self.start_time and self.end_time else None
        }
