# AI Module Architecture

This document describes the modular AI architecture implemented in the `ai` Django app.

## 🏗️ Architecture Overview

The AI module follows a factory pattern design that allows for easy scaling and provider switching. Each component is modular and can be independently configured.

```
ai/
├── llms/           # Language Model providers (OpenAI, Azure, etc.)
├── embeddings/     # Embedding providers (OpenAI, Azure, etc.)
├── chains/         # Chain implementations (conversation, retrieval, etc.)
├── memories/       # Conversation memory management
├── vector_stores/  # Vector storage providers (Elasticsearch)
├── callbacks/      # Monitoring and callbacks
├── tracing/        # Debugging and tracing
└── models.py       # Database models for persistence
```

## 🔧 Factory Pattern

### LLM Factory (`ai/llms/factory.py`)

```python
from ai.llms.factory import LLMFactory

# Create OpenAI LLM
llm = LLMFactory.create_llm(
    provider='openai',
    model_name='gpt-3.5-turbo',
    temperature=0.7
)

# Create streaming LLM
streaming_llm = LLMFactory.create_llm(
    provider='openai',
    streaming=True,
    model_name='gpt-4'
)

# Get available providers
providers = LLMFactory.get_available_providers()
```

### Embeddings Factory (`ai/embeddings/factory.py`)

```python
from ai.embeddings.factory import EmbeddingsFactory

# Create OpenAI embeddings
embeddings = EmbeddingsFactory.create_embeddings(
    provider='openai',
    model_name='text-embedding-ada-002'
)

# Create Azure embeddings
azure_embeddings = EmbeddingsFactory.create_embeddings(
    provider='azure',
    model_name='text-embedding-ada-002'
)
```

### Vector Stores Factory (`ai/vector_stores/factory.py`)

```python
from ai.vector_stores.factory import VectorStoreFactory

# Create Elasticsearch vector store
vector_store = VectorStoreFactory.create_vector_store(
    provider='elasticsearch',
    index_name='ai_documents'
)

# Create retriever
retriever = VectorStoreFactory.create_retriever(
    provider='elasticsearch',
    chat_args=chat_args,
    k=4
)
```

## 🧠 Memory Management

### SQL Message History (`ai/memories/histories/sql_history.py`)

```python
from ai.memories.histories.sql_history import SqlMessageHistory

# Create message history
history = SqlMessageHistory(conversation_id="conv-123")

# Add messages
history.add_message(HumanMessage(content="Hello"))
history.add_message(AIMessage(content="Hi there!"))

# Get messages
messages = history.messages
```

### Memory Builders (`ai/memories/`)

```python
from ai.memories.sql_memory import build_memory
from ai.memories.window_memory import window_buffer_memory_builder

# Build conversation memory
memory = build_memory(chat_args)

# Build window memory (keeps last 2 exchanges)
window_memory = window_buffer_memory_builder(chat_args)
```

## 🔗 Chain Implementations

### Streamable Chains (`ai/chains/streamable.py`)

```python
from ai.chains.streamable import StreamableChain

class MyChain(StreamableChain, BaseChain):
    def stream(self, input_data):
        # Stream tokens as they are generated
        for token in self.stream(input_data):
            yield token
```

### Traceable Chains (`ai/chains/traceable.py`)

```python
from ai.chains.traceable import TraceableChain

class MyChain(TraceableChain, BaseChain):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_metadata({'conversation_id': 'conv-123'})
```

### Retrieval Chain (`ai/chains/retrieval.py`)

```python
from ai.chains.retrieval import StreamingConversationalRetrievalChain

# Create retrieval chain
chain = StreamingConversationalRetrievalChain.from_llm(
    llm=llm,
    retriever=retriever,
    return_source_documents=True
)

# Stream retrieval results
for token in chain.stream_retrieval(question, chat_history):
    print(token)
```

## 🗄️ Vector Stores

### Elasticsearch (`ai/vector_stores/elasticsearch.py`)

```python
from ai.vector_stores.elasticsearch import build_elasticsearch_vector_store

# Initialize Elasticsearch
vector_store = build_elasticsearch_vector_store(
    index_name="ai_documents",
    elasticsearch_url="http://localhost:9200"
)
```

## 📊 Database Models

### Conversation Model

```python
from ai.conversations.models import Conversation, ConversationMessage

# Create conversation
conversation = Conversation.objects.create(
    user=user,
    title="My AI Chat"
)

# Add message
message = ConversationMessage.objects.create(
    conversation=conversation,
    role='human',
    content='Hello AI!'
)
```

### Document Model

```python
from ai.models import Document, DocumentChunk

# Create document
document = Document.objects.create(
    title="AI Guide",
    content="This is a guide about AI...",
    source="https://example.com"
)

# Create chunk
chunk = DocumentChunk.objects.create(
    document=document,
    content="AI is a technology...",
    chunk_index=0
)
```

## 🚀 API Endpoints

### Health & Status

- `GET /ai/health/` - AI module health check
- `GET /ai/status/` - Module status overview

### LLMs

- `POST /ai/llms/openai/` - OpenAI chat
- `POST /ai/llms/langchain/` - LangChain chat
- `GET /ai/llms/models/` - Available models
- `GET /ai/llms/providers/` - Available providers

### Embeddings

- `POST /ai/embeddings/create/` - Create embedding
- `POST /ai/embeddings/batch/` - Batch embeddings
- `POST /ai/embeddings/similarity/` - Similarity search
- `GET /ai/embeddings/providers/` - Available providers

### Chains

- `POST /ai/chains/conversation/` - Conversation chain
- `POST /ai/chains/qa/` - Question-Answer chain
- `POST /ai/chains/retrieval/` - Retrieval chain

### Memories

- `GET /ai/memories/conversations/` - List conversations
- `POST /ai/memories/conversations/create/` - Create conversation
- `GET /ai/memories/conversations/<id>/` - Get conversation
- `POST /ai/memories/conversations/<id>/messages/` - Add message
- `DELETE /ai/memories/conversations/<id>/clear/` - Clear conversation

### Vector Stores

- `GET /ai/vector_stores/documents/` - List documents
- `POST /ai/vector_stores/documents/create/` - Create document
- `GET /ai/vector_stores/documents/<id>/` - Get document
- `POST /ai/vector_stores/search/` - Search documents
- `GET /ai/vector_stores/providers/` - Available providers

## 🔧 Configuration

### Environment Variables

```bash
# OpenAI
OPENAI_API_KEY=your-openai-key
# Optional OpenAI tuning
OPENAI_REQUEST_TIMEOUT=60
OPENAI_MAX_RETRIES=5

# Azure OpenAI
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_API_BASE=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2023-05-15
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment

# Elasticsearch (default vector store)
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX_NAME=ai_documents
ELASTICSEARCH_USER=optional
ELASTICSEARCH_PASSWORD=optional

# Note: Pinecone support has been removed in favor of Elasticsearch
```

### Django Settings

```python
# settings.py
INSTALLED_APPS = [
    # ... other apps
    'ai',
]

# Database configuration for AI models
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'your_db',
        # ... other settings
    }
}
```

## 🧪 Testing

### Run Test Suite

```bash
# Run the comprehensive test suite
python test_ai_architecture.py

# Test specific module
python -c "
from ai.llms.factory import LLMFactory
llm = LLMFactory.create_llm(provider='openai')
print('LLM Factory working!')
"
```

### Mock Mode

All endpoints support mock mode for testing without API keys:

```python
# Enable mock mode
data = {
    'message': 'Hello AI!',
    'mock': True
}
```

## 🔄 Migration

### Create Migrations

```bash
python manage.py makemigrations ai
python manage.py migrate
```

### Database Schema

The AI module creates the following tables:

- `ai_conversations` - Conversation sessions
- `ai_conversation_messages` - Individual messages
- `ai_documents` - Documents for retrieval
- `ai_document_chunks` - Document chunks for vector search

## 🚀 Deployment

### Docker

```dockerfile
# Add to Dockerfile
RUN pip install -r requirements.txt
```

### Environment Setup

```bash
# Set environment variables
export OPENAI_API_KEY="your-key"
export ELASTICSEARCH_URL="http://localhost:9200"

# Run migrations
python manage.py migrate

# Start server
python manage.py runserver
```

## 🔍 Monitoring

### Health Checks

```bash
# Check AI module health
curl http://localhost:8000/ai/health/

# Check module status
curl http://localhost:8000/ai/status/
```

### Logging

The AI module includes comprehensive logging for:

- API calls and responses
- Error handling
- Performance metrics
- Trace information

## 🤝 Contributing

### Adding New Providers

1. Create provider module in appropriate directory
2. Implement factory methods
3. Add to factory registry
4. Update tests
5. Update documentation

### Example: Adding Anthropic

```python
# ai/llms/anthropic.py
from langchain_community.llms import Anthropic

def build_anthropic_llm(chat_args=None, **kwargs):
    return Anthropic(**kwargs)

# ai/llms/factory.py
PROVIDERS = {
    'openai': {...},
    'azure': {...},
    'anthropic': {'llm': build_anthropic_llm}
}
```

## 📚 Examples

### Complete Chat Flow

```python
from ai.llms.factory import LLMFactory
from ai.memories.sql_memory import build_memory
from ai.chains.retrieval import StreamingConversationalRetrievalChain

# Create components
llm = LLMFactory.create_llm(provider='openai')
memory = build_memory(chat_args)
retriever = VectorStoreFactory.create_retriever(provider='elasticsearch')

# Create chain
chain = StreamingConversationalRetrievalChain.from_llm(
    llm=llm,
    retriever=retriever,
    memory=memory
)

# Stream response
for token in chain.stream_retrieval("What is AI?", chat_history):
    print(token, end='')
```

This architecture provides a scalable, maintainable foundation for AI functionality that can easily adapt to new providers and requirements.
