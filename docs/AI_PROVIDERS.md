# AI provider adapter

`OpenAICompatibleProvider` implements the read-only chat-completions contract in
`kiprod.ai.provider.LLMProvider`. It sends a non-streaming JSON request through the
provided `HttpClient`, returns provider/model/token metadata, and never retries or
silently changes the requested model. KiProd validates structured output locally.

## HTTPS endpoint

```python
import os

from kiprod.ai.openai_compatible import OpenAICompatibleProvider
from kiprod.net.http import HttpClient

provider = OpenAICompatibleProvider(
    base_url="https://api.example.test/v1",
    model="configured-model-name",
    api_key=os.environ["KIPROD_AI_API_KEY"],
    http=HttpClient({"api.example.test"}),
)
```

Only the configured hostname is allowed. The API key is sent as a bearer header,
never in a URL. Configure any per-million-token rates explicitly if cost estimation
is desired; otherwise estimates are unknown (`None`).

## Local Ollama-compatible endpoint

```python
from kiprod.ai.openai_compatible import OpenAICompatibleProvider
from kiprod.net.http import HttpClient

provider = OpenAICompatibleProvider(
    base_url="http://127.0.0.1:11434/v1",
    model="local-model-name",
    provider_name="ollama",
    http=HttpClient({"127.0.0.1"}, allow_local_http=True),
)
```

Unencrypted HTTP is accepted only for `localhost` or an IP loopback address, and
only when the client explicitly enables it and allowlists the host. Cross-origin
redirects are rejected. The provider reports itself as local only for loopback
hosts, which lets `review_bom(..., confidential=True)` reject remote providers.

When a JSON schema is supplied, the adapter requests JSON object mode and KiProd
validates the response against its strict Pydantic model. This adapter does not
claim server-side JSON Schema enforcement, tool calling, caching, vision, or native
provider-specific features. Native OpenAI Responses and Anthropic adapters remain
future work.

The request and local Ollama compatibility behavior follow the [OpenAI chat API
reference](https://developers.openai.com/api/reference/resources/chat) and [Ollama's
OpenAI compatibility documentation](https://docs.ollama.com/api/openai-compatibility).

## Roles, budgets, and cache

`AIRequestManager` binds providers to `reasoning`, `extraction`, `writer`, and
`local_only` roles. Each role sets its provider, model identity, and output-token
limit. The manager can also set run-wide token and cost limits:

```python
from kiprod.ai.provider import Message
from kiprod.ai.runtime import AIRequestManager, RolePolicy

manager = AIRequestManager(
    {"local_only": RolePolicy(provider, "local-model-name", max_output_tokens=1000,
                               local_only=True)},
    max_run_tokens=12000,
)
messages = [Message(role="user", content="Review the normalized BOM.")]
plan = manager.plan("local_only", messages, max_tokens=500)
if plan.allowed:
    result = manager.complete("local_only", messages, max_tokens=500)
```

Budget planning uses UTF-8 byte length plus message framing as a conservative upper
bound for prompt tokens and reserves the requested maximum output. If a cost limit is configured,
the provider must have explicit token rates; unknown pricing fails closed. Repeated
identical requests reuse a SHA-256 keyed result in memory for the lifetime of the
manager. The key includes role, provider, model, messages, schema, token limit, and
temperature. No result cache is written to disk.
