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
provider-specific features.

The request and local Ollama compatibility behavior follow the [OpenAI chat API
reference](https://developers.openai.com/api/reference/resources/chat) and [Ollama's
OpenAI compatibility documentation](https://docs.ollama.com/api/openai-compatibility).

## Native provider adapters

For OpenAI's Responses API, the adapter sends `store: false` and supports strict
JSON Schema output:

```python
import os

from kiprod.ai.openai_responses import OpenAIResponsesProvider
from kiprod.net.http import HttpClient

provider = OpenAIResponsesProvider(
    api_key=os.environ["OPENAI_API_KEY"],
    model="configured-model-name",
    http=HttpClient({"api.openai.com"}),
)
```

For Anthropic's Messages API, the adapter sends the required API version and API
key headers. Its version defaults to `2023-06-01` and can be configured when
constructing the provider.

```python
import os

from kiprod.ai.anthropic import AnthropicProvider
from kiprod.net.http import HttpClient

provider = AnthropicProvider(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    model="configured-model-name",
    http=HttpClient({"api.anthropic.com"}),
)
```

Both native adapters support JSON Schema requests and return reported token usage.
Responses still pass through KiProd's Pydantic validation before the review layer
accepts them. The Anthropic adapter currently leaves sampling temperature at the
provider default for compatibility with newer model families. Fixture tests never
make live provider calls.

The native request shapes follow the [OpenAI Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create), [Anthropic Messages API authentication requirements](https://platform.claude.com/docs/en/manage-claude/authentication), and [Anthropic structured output format](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

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

## Versioned prompt overrides

Prompts are Markdown files with YAML-style scalar front matter. A BOM review prompt
can be overridden by passing search directories in precedence order; the bundled
`kiprod/prompts/bom_review.md` is the final fallback:

```markdown
---
role: reasoning
schema: bom_review_v1
version: project-1
---
Review electrical and manufacturing risks. Cite the supplied BOM line IDs.
```

```python
report = review_bom(
    bom,
    provider=provider,
    prompt_dirs=[project_root / "kiprod" / "prompts", supplier_plugin / "prompts"],
)
```

The first matching directory wins. Prompt task names are path-checked, files are
limited to 64 KiB, front matter only accepts `role`, `schema`, and `version`, and
the loaded prompt version is stored with each AI finding and the review report.
Prompt text and BOM data remain separate messages; the BOM payload omits arbitrary
fields, resolved values, and project input hashes.

## Model evaluation

The labeled review fixture set is in `tests/fixtures/ai_review/`. Evaluate a local
OpenAI-compatible server with:

```bash
./scripts/run.sh ai eval compatible \
  --base-url http://127.0.0.1:11434/v1 \
  --model local-model-name \
  --max-run-tokens 20000 \
  --output /tmp/kiprod-ai-evaluation.json
```

The command makes live requests to the selected provider. Native OpenAI and
Anthropic modes read their API keys from `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`
by default; `--api-key-env` selects another environment variable. Set
`--max-run-cost` with explicit per-million token rates to enforce a cost cap; if the
provider price is unknown, the budget manager blocks the request. The report
includes schema-valid rate, exact finding precision/recall/F1, citation grounding,
and per-fixture errors. Tests use a fixture provider and do not make live calls.
