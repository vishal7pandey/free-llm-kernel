# DFMEA — Free LLM Client Wrapper

**System:** `C:\Dev\services\llm.py` (v0.1.0)
**Date:** 2026-07-18
**Analyst:** Cascade + User
**Scope:** All 12 assemblies of the LLM wrapper, analyzed against actual code

---

## Scoring Scale

| Score | Severity (S) | Occurrence (O) | Detection (D) |
|-------|-------------|----------------|---------------|
| 1 | No effect | Impossible | Certain detection |
| 2-3 | Minor inconvenience | Rare | High detection probability |
| 4-6 | Moderate degradation | Occasional | Moderate detection |
| 7-8 | High severity | Frequent | Low detection |
| 9-10 | Catastrophic / data loss | Inevitable | Undetectable |

**RPN = S × O × D** (Risk Priority Number, max 1000)
- **RPN ≥ 100**: Critical — fix before use
- **RPN 50–99**: High — fix soon
- **RPN 20–49**: Medium — track and address
- **RPN < 20**: Low — acceptable risk

---

## Assembly-to-Code Mapping

| # | Assembly | Code Location | Status |
|---|----------|--------------|--------|
| 1 | Client Interface | `chat()` signature, `__init__.py` | Minimal |
| 2 | Request Processing | `chat()` L291-294, kwargs passthrough | Minimal |
| 3 | Provider Management | `Provider` dataclass, `PROVIDERS` list | Basic |
| 4 | Routing Engine | `chat()` L296-308, priority sort | Basic |
| 5 | Execution Engine | `chat()` L310-326, `_stream()` L336-356 | Basic |
| 6 | Response Processing | L326, `_stream()` delta extraction | Minimal |
| 7 | State Management | `_load_usage`, `_save_usage`, `.usage.json` | Basic |
| 8 | Observability | `print_usage()`, `usage()` | Minimal |
| 9 | Security | `.env` loading, `is_configured` | Minimal |
| 10 | Configuration | `PROVIDERS`, `DAILY_LIMITS`, `.env` | Basic |
| 11 | Resilience | try/except fallback L328-330 | Basic |
| 12 | Extensibility | `providers` param, `**kwargs` | Minimal |

---

## DFMEA Worksheets

### Assembly 4: Routing Engine (Highest Risk)

**Code:** `chat()` L296-308, `__init__` L179-188, `_is_exhausted()` L246-252

| ID | Failure Mode | Effect (What happens) | Cause (Why) | S | O | D | RPN | Category | Recommended Control |
|----|-------------|----------------------|------------|---|---|---|-----|----------|-------------------|
| R-01 | Provider selected by static priority only — no health/latency awareness | User always hits Groq first even if Groq is down/slow, wasting time before fallback | No health monitor, no latency history. `self._active.sort(key=lambda p: p.priority)` L187 is the only routing logic | 6 | 8 | 2 | 96 | C | Add health check ping + latency tracking per provider. Score = f(health, latency, quota_remaining) |
| R-02 | Exhausted provider skipped but no feedback to caller | User doesn't know why their request was slow (silently skipped 3 providers) | `_is_exhausted()` L307 silently `continue`s with no logging | 4 | 7 | 7 | 196 | N | Log skipped providers. Return routing metadata in response or via callback |
| R-03 | All providers exhausted → RuntimeError with no recovery guidance | User gets cryptic error, doesn't know which keys to add or limits to raise | L332-334 raises `RuntimeError` with last error only. No actionable info | 7 | 5 | 4 | 140 | M | Include exhaustion summary in error: which providers hit limits, which failed, suggested actions |
| R-04 | Forced provider (`provider="groq"`) doesn't check exhaustion | User forces Groq, but Groq is exhausted — gets error instead of fallback | L296-301 filters candidates by name only, doesn't fall through to other providers if the forced one is exhausted | 5 | 6 | 5 | 150 | C | When forced provider is exhausted, either warn and fallback or return a clear "provider exhausted" error with usage stats |
| R-05 | Model name not validated against provider's supported list | User passes `model="gpt-4"` to Groq → 400 error → fallback to next provider with wrong model | L312 `use_model = model or prov.default_model` — no validation against `prov.models` | 6 | 5 | 6 | 180 | C | Validate requested model against provider's model list. If unsupported, skip provider or map to equivalent |
| R-06 | No capability-based routing (tools, vision, JSON mode) | User needs function calling but gets Gemini Flash which may not support it → silent failure or error | No capability metadata in `Provider` dataclass. Routing is priority-only | 7 | 4 | 7 | 196 | C/L | Add `capabilities` field to Provider (tools, vision, json_mode, streaming, max_context). Filter candidates by required capabilities |
| R-07 | Priority order is arbitrary, not optimized | Cerebras (30 req/day) tried before Mistral (100 req/day) — burns scarce quota first | Static `priority` field. No quota-aware ordering | 4 | 7 | 3 | 84 | C/K | Sort candidates by remaining quota descending (quota-aware routing) before trying |
| R-08 | No context-length awareness in routing | User sends 100k-token prompt, routed to Cloudflare (4-8k context) → error → fallback | No token estimation, no max_context in Provider | 7 | 5 | 6 | 210 | B/C | Add `max_context` to Provider. Estimate input tokens. Skip providers whose context is too small |
| R-09 | Routing table is static — never updated at runtime | New free models added by providers are never discovered. Dead models stay in rotation | `PROVIDERS` is a hardcoded list. No `/models` discovery | 5 | 6 | 4 | 120 | C/O | Add optional model discovery via provider `/models` endpoints. Cache results. See `freelm` approach |
| R-10 | Single LLMClient instance shares usage state across threads | Concurrent requests in multi-threaded app corrupt `.usage.json` | `_usage` dict is in-memory, `_save_usage` writes to disk with no locking | 7 | 4 | 7 | 196 | J/M | Add file locking or atomic writes. Or use `threading.Lock` around usage operations |

**Assembly RPN Summary:** 9 failure modes, 5 critical (RPN ≥ 100), highest RPN = 210

---

### Assembly 5: Execution Engine

**Code:** `chat()` L310-326, `_stream()` L336-356, `_get_client()` L254-261

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| E-01 | No timeout on API calls | Request hangs indefinitely if provider is unresponsive | `OpenAI()` client created L261 with no `timeout` param. Default is 600s | 8 | 5 | 4 | 160 | E/J | Set `timeout=30` (or configurable) on OpenAI client construction |
| E-02 | Streaming failure mid-stream — no fallback | Provider drops connection at token 500 of 1000 → user gets partial response, no retry | `_stream()` L336-356 is a generator. Once `yield` starts, the `chat()` loop's try/except can't catch errors inside the generator | 8 | 6 | 7 | 336 | E/F | Wrap stream in try/except inside `_stream()`. On error, yield an error marker or raise a catchable exception. Consider buffering first N tokens before yielding |
| E-03 | Usage counted before stream completes | Provider fails mid-stream but usage was already incremented at L315 | `self._increment_usage(prov.name)` called before `_stream()` returns | 5 | 7 | 5 | 175 | K | Increment usage after stream completes, or decrement on failure |
| E-04 | No retry within a provider before fallback | Transient 500 error on Groq → immediately falls to next provider (possibly worse model) | L328-330 catches error and `continue`s to next provider. No retry within provider | 5 | 6 | 3 | 90 | E/M | Add 1-2 retries with exponential backoff per provider before falling back |
| E-05 | Cloudflare base_url not validated | `CF_ACCOUNT_ID` is empty or wrong → malformed URL → connection error → fallback | L256-258 replaces `{CF_ACCOUNT_ID}` with env var. No validation that it's set | 4 | 4 | 6 | 96 | D/O | Validate `CF_ACCOUNT_ID` is set when Cloudflare provider is configured. Log warning if missing |
| E-06 | OpenAI client created per-request, not pooled | Every `chat()` call creates a new `OpenAI()` instance → connection overhead | `_get_client()` L254-261 returns a new client every call | 3 | 8 | 3 | 72 | J | Cache OpenAI clients per provider in a dict. Reuse across requests |
| E-07 | `**kwargs` passed through without validation | User passes `top_p=-5` or unknown param → provider returns 400 → fallback loop | L323 `**kwargs` passed directly to `client.chat.completions.create()` | 4 | 4 | 5 | 80 | A/L | Validate kwargs against a whitelist of supported parameters |
| E-08 | No concurrency support — requests are sequential | If used in async context, blocks the event loop | `chat()` is synchronous. `_stream()` uses synchronous iterator | 5 | 5 | 4 | 100 | J | Add `async def achat()` and `async def astream()` variants using `AsyncOpenAI` |
| E-09 | Empty response from provider returns empty string silently | Provider returns `null` content → user gets `""` with no error | L326 `response.choices[0].message.content or ""` | 5 | 3 | 7 | 105 | F | Check for empty/null content. Log warning. Optionally retry on different provider |
| E-10 | `response.choices` could be empty list | Provider returns 200 but with empty `choices` array → IndexError | L326 `response.choices[0]` — no bounds check | 7 | 3 | 6 | 126 | F | Check `len(response.choices) > 0` before accessing |

**Assembly EPN Summary:** 10 failure modes, 6 critical (RPN ≥ 100), highest RPN = 336

---

### Assembly 3: Provider Management

**Code:** `Provider` dataclass L55-72, `PROVIDERS` L75-166, `is_configured` L69-72

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| P-01 | API key marked as "your-key-here" passes validation if user adds extra whitespace | Wrapper thinks provider is configured, calls fail with 401 | L72 checks `key.strip() != "your-key-here"` but `your-key-here ` (trailing space) would pass | 4 | 3 | 6 | 72 | D/O | Use `key.strip().lower() != "your-key-here"` and check for placeholder patterns |
| P-02 | No API key validation at startup | Invalid/expired keys discovered only at first request time | `is_configured` L69-72 only checks key is present, not valid | 5 | 6 | 5 | 150 | D | Add optional startup health check: send a tiny test prompt to each configured provider. Log results |
| P-03 | Provider deprecates a model — no detection | Model name in `PROVIDERS` becomes invalid → 400 error → fallback | Model names are hardcoded (e.g. `llama-3.3-70b-versatile`). No validation | 6 | 5 | 5 | 150 | D/L | Add model discovery via `/models` endpoint. Cache. Fallback to default if model not found |
| P-04 | No provider capability metadata | Can't route based on what provider supports (tools, vision, JSON mode, streaming) | `Provider` dataclass has no `capabilities` field | 7 | 5 | 7 | 245 | C/L | Add `capabilities: dict` field (tools, vision, json_mode, streaming, max_context_tokens) |
| P-05 | Provider base_url changes — no detection | Provider moves API endpoint → all requests fail | URLs are hardcoded in `PROVIDERS` list | 6 | 3 | 6 | 108 | D/L | Make URLs configurable via env vars with hardcoded defaults |
| P-06 | Ollama provider always "configured" if `OLLAMA_API_KEY=ollama` | Wrapper tries Ollama even when `ollama serve` isn't running → connection error | L260 `api_key = provider.api_key or "ollama"` — Ollama key defaults to "ollama" string, passes `is_configured` | 5 | 6 | 4 | 120 | D/O | For Ollama, check if `localhost:11434` is reachable at startup. Don't include in active providers if not |
| P-07 | No mechanism to disable a provider at runtime | Provider goes down, user wants to skip it temporarily — must restart or edit `.env` | No runtime enable/disable. `_active` is set once in `__init__` | 4 | 5 | 4 | 80 | O | Add `disable_provider(name)` / `enable_provider(name)` methods |
| P-08 | Daily limits are hardcoded, not sourced from provider | Provider changes their free tier limits → wrapper uses stale limits → over/under-uses provider | `DAILY_LIMITS` dict L41-52 is static | 3 | 5 | 5 | 75 | K/O | Make limits configurable via env vars or config file. Allow runtime override |
| P-09 | No per-provider error history | Can't diagnose which provider fails most often | No error tracking. `last_error` L329 only keeps the most recent | 4 | 6 | 6 | 144 | N | Add error counter per provider. Store in usage file. Surface in `usage()` |
| P-10 | Provider returns non-OpenAI-compatible response | Some providers may deviate from OpenAI schema → parsing error | All providers assumed OpenAI-compatible. No response schema validation | 6 | 3 | 7 | 126 | F/L | Validate response has `choices[0].message.content`. Handle non-standard responses gracefully |

**Assembly RPN Summary:** 10 failure modes, 5 critical (RPN ≥ 100), highest RPN = 245

---

### Assembly 7: State Management

**Code:** `_load_usage()` L218-229, `_save_usage()` L231-236, `_increment_usage()` L238-244, `_is_exhausted()` L246-252

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| S-01 | `.usage.json` corrupted → usage data lost | All counters reset to 0 → providers not marked as exhausted → quota burn | L222 `json.loads()` can fail on partial write. L227 catches `JSONDecodeError` but resets to empty | 5 | 4 | 5 | 100 | H | Use atomic write (write to temp file, then rename). Or use SQLite |
| S-02 | Usage file grows unbounded — old days never cleaned | File gets large over months → slow load/save | L218-229 loads entire file. Never prunes old dates | 2 | 5 | 6 | 60 | J/H | Prune entries older than 7 days on load. Keep only recent history |
| S-03 | No file locking — concurrent processes corrupt usage file | Two scripts running simultaneously → lost increments → wrong counts | `_save_usage()` L231-236 does plain `write_text()`. No `fcntl`/`msvcrt` locking | 6 | 4 | 7 | 168 | H/M | Use `filelock` library or atomic write pattern. Or switch to SQLite with WAL mode |
| S-04 | Usage counter not incremented on failed requests — but is for streaming | Non-stream: counted on success (L325). Stream: counted before completion (L315). Inconsistent. | Different increment points for stream vs non-stream | 4 | 6 | 6 | 144 | K | Unify: increment after successful response in both paths. For stream, increment in `_stream()` after completion |
| S-05 | Date boundary race — request at 23:59:59, increment at 00:00:01 | Counter attributed to wrong day → today's count is wrong | `str(date.today())` called at L240 in `_increment_usage`. If request starts before midnight but increments after, it counts toward new day | 2 | 3 | 7 | 42 | K | Capture timestamp at request start, use that for usage attribution |
| S-06 | No conversation/session state | Can't maintain multi-turn conversations without re-sending full history each time | `chat()` takes a single `prompt` string. No session management | 6 | 8 | 3 | 144 | H | Add optional `Session` class that maintains message history and sends full context per request |
| S-07 | `.usage.json` path is relative to module — breaks if module is moved | Usage file not found → counters reset silently | L37 `_USAGE_FILE = Path(__file__).parent / ".usage.json"` — tied to module location | 3 | 3 | 5 | 45 | O | Make path configurable via env var `LLM_USAGE_FILE` with current as default |
| S-08 | No token accounting — only request counts | Can't track actual token usage per provider. Quota limits are token-based for some providers (Cerebras, Cloudflare) | `_increment_usage()` L238-244 only counts requests, not tokens | 5 | 8 | 4 | 160 | K | Extract `usage.prompt_tokens` and `usage.completion_tokens` from response. Track per provider per day |

**Assembly RPN Summary:** 8 failure modes, 4 critical (RPN ≥ 100), highest RPN = 168

---

### Assembly 11: Resilience

**Code:** try/except fallback L328-330, `RuntimeError` L332-334

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| X-01 | Only 3 exception types caught — others crash the wrapper | `AuthenticationError`, `PermissionDeniedError`, `BadRequestError` (subclass of APIStatusError?) or `APITimeoutError` not caught → unhandled exception | L328 catches `RateLimitError, APIConnectionError, APIStatusError`. Missing: `APITimeoutError`, `AuthenticationError` | 7 | 5 | 5 | 175 | D/E/M | Catch broader `OpenAIError` base class or add specific missing exceptions |
| X-02 | No retry within provider — single attempt then fallback | Transient 502 on Groq → immediately switch to Google (different model, different quality) | L328-330 catches and `continue`s. No retry logic | 5 | 6 | 3 | 90 | E/M | Add configurable retry count (default 2) with exponential backoff before fallback |
| X-03 | No circuit breaker — keeps trying dead providers | Provider is down for hours → every request wastes time attempting it before fallback | No circuit breaker. Every `chat()` call tries all active providers in order | 6 | 5 | 5 | 150 | M | Add simple circuit breaker: after N consecutive failures, skip provider for cooldown period (e.g. 5 min) |
| X-04 | Fallback error message loses context | User sees "All providers failed. Last error: ..." — only last error, not all failures | L332-334 only includes `last_error`. No error aggregation | 4 | 5 | 5 | 100 | N/M | Collect all errors in a list. Include per-provider failure summary in error message |
| X-05 | No graceful degradation — all-or-nothing | If all providers fail, hard error. No fallback to simpler model, cached response, or queue | L332-334 raises `RuntimeError`. No degradation strategy | 6 | 4 | 5 | 120 | M | Add optional fallback to local Ollama with smaller model. Or queue request for retry |
| X-06 | No exponential backoff between fallback attempts | Rapid-fire requests to 10 providers in <1 second → may trigger rate limits on all | L306-330 loops through providers with no delay between attempts | 5 | 4 | 5 | 100 | E/M | Add small delay (0.5s) between provider attempts. Exponential backoff if retrying same provider |
| X-07 | Streaming has no resilience at all | Stream error after first token → generator raises, caller gets traceback | `_stream()` L336-356 has no try/except. Errors propagate unhandled | 8 | 5 | 7 | 280 | E/F/M | Wrap `_stream()` in try/except. On error, either raise a specific exception or attempt fallback (harder for streaming) |

**Assembly RPN Summary:** 7 failure modes, 5 critical (RPN ≥ 100), highest RPN = 280

---

### Assembly 2: Request Processing

**Code:** `chat()` L291-294, kwargs L273, L323

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| Q-01 | Empty prompt accepted silently | Empty string sent to provider → wasted API call or error | L291-294 constructs messages with no validation of `prompt` | 3 | 4 | 6 | 72 | A | Validate `prompt` is non-empty string. Raise `ValueError` if empty |
| Q-02 | No token estimation — can't prevent oversized requests | 200k-token prompt sent to 8k-context provider → error → fallback loop | No tokenizer, no `max_context` in Provider. L291-294 just builds messages | 7 | 5 | 6 | 210 | B/C | Add `tiktoken` for token estimation. Store `max_context` per provider. Reject or warn if prompt exceeds smallest context |
| Q-03 | System prompt not merged intelligently | If provider doesn't support system role (some don't), request fails | L292-293 adds system message unconditionally. No capability check | 4 | 3 | 6 | 72 | B/L | Check if provider supports system messages. If not, prepend to user message |
| Q-04 | No message history support — single prompt only | User can't send multi-turn conversation without manually constructing messages | `chat()` takes `prompt: str` only. No `messages: list` parameter | 6 | 7 | 3 | 126 | B/H | Add optional `messages` parameter. If provided, use directly instead of constructing from prompt+system |
| Q-05 | Temperature not clamped to valid range | User passes `temperature=15` → provider returns 400 → fallback | L271 `temperature: float = 0.7` — no validation | 3 | 3 | 6 | 54 | A | Clamp temperature to [0.0, 2.0]. Same for other params |
| Q-06 | `max_tokens` not validated against provider limit | User requests `max_tokens=100000` from an 8k model → error or truncation | L272 `max_tokens: int | None = None` — no per-provider limit | 4 | 4 | 5 | 80 | A/L | Store `max_output_tokens` per provider. Clamp or warn |
| Q-07 | No support for multi-modal input (images) | User can't send images to vision-capable providers | `chat()` only accepts `prompt: str`. No image/content type support | 5 | 5 | 3 | 75 | A/L | Add optional `images: list` parameter. Construct multi-content messages for vision-capable providers |
| Q-08 | kwargs not type-checked | User passes `top_p="high"` (string) → serialization error deep in OpenAI SDK | L273 `**kwargs` passed through with no type checking | 3 | 3 | 5 | 45 | A | Validate kwarg types against OpenAI API spec. Or document supported kwargs |

**Assembly RPN Summary:** 8 failure modes, 2 critical (RPN ≥ 100), highest RPN = 210

---

### Assembly 6: Response Processing

**Code:** L326, `_stream()` L353-356

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| F-01 | `response.choices[0]` IndexError on empty choices | Unhandled exception, caller gets traceback | L326 no bounds check | 7 | 3 | 6 | 126 | F | Check `len(response.choices) > 0`. Raise descriptive error if empty |
| F-02 | `message.content` is `None` → returns `""` silently | User gets empty string, doesn't know if model returned nothing or errored | L326 `or ""` masks None | 5 | 3 | 7 | 105 | F | Distinguish: None content → log warning + retry on next provider. Empty string → return as-is |
| F-03 | Streaming delta.content is None for first chunk | First chunk has no content (role only) → `if delta.content` handles it, but no issue. However, `chunk.choices[0]` could fail on final chunk | L353-356 `chunk.choices[0].delta` — no bounds check per chunk | 5 | 4 | 6 | 120 | F | Check `len(chunk.choices) > 0` and `chunk.choices[0].delta is not None` per chunk |
| F-04 | No tool call parsing in response | Provider returns tool calls but wrapper only extracts `content` → tool calls lost | L326 only reads `.message.content`. No `.message.tool_calls` handling | 6 | 4 | 5 | 120 | F/G | Check for `tool_calls` in response. Return structured object with content + tool_calls |
| F-05 | No JSON mode response validation | User requests `response_format={"type": "json_object"}` but gets malformed JSON | No JSON validation in response processing | 4 | 3 | 6 | 72 | F | If `response_format` is JSON, validate output is parseable JSON. Retry if not |
| F-06 | No `finish_reason` check | Response truncated due to `max_tokens` → user gets incomplete text with no indication | L326 doesn't check `response.choices[0].finish_reason` | 5 | 5 | 6 | 150 | F | Check `finish_reason`. If `"length"`, warn user about truncation. If `"content_filter"`, try different provider |
| F-07 | Provider returns non-UTF8 or encoded content | Special characters garbled in output | No encoding validation. OpenAI SDK usually handles this, but custom providers may not | 3 | 2 | 7 | 42 | F | Validate response is valid UTF-8. Strip or replace invalid sequences |
| F-08 | No usage/token extraction from response | Can't track actual token consumption per request | L326 doesn't read `response.usage` | 4 | 7 | 4 | 112 | K/N | Extract `response.usage.prompt_tokens` and `completion_tokens`. Feed into state management |

**Assembly RPN Summary:** 8 failure modes, 4 critical (RPN ≥ 100), highest RPN = 150

---

### Assembly 1: Client Interface

**Code:** `chat()` signature L263-274, `__init__.py`

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| C-01 | No async interface — blocks event loop | Can't be used in FastAPI, asyncio, or any async application | `chat()` is sync only. No `achat()` variant | 6 | 7 | 3 | 126 | J | Add `AsyncLLMClient` or `achat()` using `openai.AsyncOpenAI` |
| C-02 | Return type is `str | Iterator[str]` — ambiguous | Caller doesn't know if they got a string or iterator without type checking | L274 `-> str | Iterator[str]` | 3 | 5 | 4 | 60 | A | Use separate methods: `chat()` → str, `stream()` → Iterator[str] |
| C-03 | No structured response object — just a string | Caller can't access metadata (provider used, model, tokens, latency) | L326 returns bare string | 5 | 6 | 4 | 120 | N | Return `LLMResponse` dataclass with `.content`, `.provider`, `.model`, `.usage`, `.latency_ms` |
| C-04 | No batch interface | User must loop manually for multiple prompts | No `batch_chat()` method | 3 | 5 | 4 | 60 | J | Add `batch_chat(prompts: list[str])` with concurrent execution |
| C-05 | No CLI tool | Can't test from command line without writing Python | No `__main__` block or CLI entry point | 2 | 6 | 3 | 36 | O | Add `python -m services.llm "prompt"` CLI interface |
| C-06 | No OpenAI-compatible server mode | Can't point existing tools (Cursor, Continue, etc.) at it | No proxy server. Only a library | 4 | 5 | 3 | 60 | O | Add optional `serve()` method that starts a FastAPI server with `/v1/chat/completions` endpoint |

**Assembly RPN Summary:** 6 failure modes, 2 critical (RPN ≥ 100), highest RPN = 126

---

### Assembly 9: Security

**Code:** `.env` loading L35, `is_configured` L69-72, `.gitignore`

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| SEC-01 | API keys in `.env` could be logged in error messages | `last_error` L329 may contain request headers with API key | OpenAI SDK error messages may include URL/auth info. L333 includes `last_error` in RuntimeError | 8 | 3 | 7 | 168 | I | Sanitize error messages. Strip API keys, Authorization headers from error strings before surfacing |
| SEC-02 | `load_dotenv()` at module import time — keys loaded before any validation | Keys in environment even if module is imported but not used | L35 `load_dotenv()` runs at import time | 3 | 5 | 5 | 75 | I/O | Move `load_dotenv()` into `LLMClient.__init__()` so it only loads when client is created |
| SEC-03 | No prompt injection protection | Malicious prompt could cause provider to leak system info or execute unwanted actions | No input sanitization. L291-294 passes prompt directly | 6 | 4 | 7 | 168 | I | Add optional prompt sanitizer. At minimum, document the risk. Consider system prompt guardrails |
| SEC-04 | `.env` file permissions not checked | Other users on system can read API keys | No file permission check on `.env` | 5 | 3 | 7 | 105 | I | Check `.env` file permissions on POSIX. Warn if world-readable. On Windows, check ACLs |
| SEC-05 | API keys visible in process environment | Any subprocess or debug dump can see all keys via `env` | Standard env var usage. No alternative key store | 4 | 5 | 4 | 80 | I | Document risk. Consider keyring integration for production use |
| SEC-06 | No output validation — provider could return harmful content | Provider returns malicious content (e.g., script injection) that gets passed to end user | L326 returns raw content with no filtering | 4 | 3 | 6 | 72 | I | Add optional output filter. Document that content is not sanitized |

**Assembly RPN Summary:** 6 failure modes, 3 critical (RPN ≥ 100), highest RPN = 168

---

### Assembly 10: Configuration

**Code:** `PROVIDERS` L75-166, `DAILY_LIMITS` L41-52, `.env`

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| CFG-01 | Adding a provider requires editing source code | User must modify `llm.py` to add a new provider — error-prone | `PROVIDERS` is a hardcoded Python list L75-166 | 4 | 6 | 3 | 72 | P/O | Load providers from a `providers.yaml` or `providers.json` config file. Fall back to hardcoded defaults |
| CFG-02 | No config file — all settings in source | Can't change models, limits, priorities without code edit | No external config file | 4 | 6 | 4 | 96 | O | Add `config.yaml` for providers, limits, routing strategy, defaults |
| CFG-03 | No environment-based config override | Can't change behavior without restarting | No runtime config. All static | 3 | 5 | 4 | 60 | O | Support env var overrides: `LLM_DEFAULT_PROVIDER`, `LLM_TIMEOUT`, `LLM_MAX_RETRIES` |
| CFG-04 | `DAILY_LIMITS` may be wrong — provider changed their free tier | Over/under-use of providers | L41-52 hardcoded. No source of truth | 4 | 5 | 5 | 100 | K/O | Make limits configurable. Add link to provider docs in comments. Allow env override |
| CFG-05 | No validation of `.env` file at startup | Typos in key names silently ignored → provider not configured | `is_configured` checks key value, not key name. `GROQ_APIKEY` typo → Groq not active, no warning | 4 | 5 | 6 | 120 | O/D | At startup, check for common env var typos. Warn about keys in `.env.example` not found in environment |
| CFG-06 | No default model fallback chain | If `default_model` is unavailable, no secondary model tried | Each Provider has one `default_model`. No fallback within provider | 4 | 4 | 5 | 80 | C | Try `models[0]`, then `models[1]`, etc. within a provider before falling back to next provider |

**Assembly RPN Summary:** 6 failure modes, 2 critical (RPN ≥ 100), highest RPN = 120

---

### Assembly 8: Observability

**Code:** `print_usage()` L209-216, `usage()` L194-207, `available_providers()` L190-192

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| O-01 | No logging — all failures are silent | User can't diagnose why requests fail or which provider was used | No `logging` module usage. No structured logs | 6 | 7 | 5 | 210 | N | Add `logging` with configurable level. Log: provider selected, provider skipped (reason), provider failed (error), response received |
| O-02 | No metrics export | Can't monitor usage in Grafana/Prometheus | No metrics interface. Only `print_usage()` | 3 | 5 | 4 | 60 | N | Add optional Prometheus metrics exporter or structured JSON logs |
| O-03 | No per-request tracing | Can't trace a request through the fallback chain | No request ID, no trace data | 5 | 6 | 5 | 150 | N | Generate request ID per `chat()` call. Log provider attempts with request ID. Optionally support OpenTelemetry |
| O-04 | `print_usage()` uses `print()` not `logging` | Can't redirect output, can't filter by level | L209-216 uses `print()` directly | 2 | 5 | 4 | 40 | N | Use `logging.info()` instead of `print()`. Or return formatted string |
| O-05 | No latency tracking | Can't identify slow providers | No timing in `chat()` or `_stream()` | 4 | 6 | 5 | 120 | N/J | Record `time.perf_counter()` before/after each provider attempt. Store in usage file. Surface in `usage()` |
| O-06 | No error categorization | Can't distinguish auth errors from rate limits from network errors | L329 `last_error = e` — no categorization | 4 | 5 | 6 | 120 | N | Categorize errors: auth, rate_limit, network, server_error, content_filter. Track per provider |

**Assembly RPN Summary:** 6 failure modes, 3 critical (RPN ≥ 100), highest RPN = 210

---

### Assembly 12: Extensibility

**Code:** `providers` param in `__init__` L179, `**kwargs` in `chat()` L273

| ID | Failure Mode | Effect | Cause | S | O | D | RPN | Category | Recommended Control |
|----|-------------|--------|------|---|---|---|-----|----------|-------------------|
| EXT-01 | No provider plugin interface — must subclass or edit source | Adding a custom provider requires understanding internal code | `Provider` is a dataclass, not an abstract interface. No `BaseProvider` | 4 | 5 | 4 | 80 | P | Define `BaseProvider` ABC with `chat()`, `stream()`, `is_configured()`, `models()` methods. `Provider` becomes the default implementation |
| EXT-02 | No middleware/hook system | Can't intercept requests for logging, caching, rate limiting | No middleware support. `chat()` is monolithic | 4 | 5 | 5 | 100 | P | Add optional `middlewares: list` param. Each middleware wraps `chat()`: `before(request)`, `after(response)`, `on_error(error)` |
| EXT-03 | No custom router support | Can't implement custom routing logic (e.g., cheapest, fastest, best quality) | Routing is hardcoded as priority sort L187 | 4 | 5 | 4 | 80 | P/C | Add `routing_strategy` param: `"priority"`, `"quota_aware"`, `"latency"`, `"round_robin"`, or callable |
| EXT-04 | `**kwargs` is the only extension point for request params | No structured way to add provider-specific params | L273 `**kwargs` — untyped, undocumented | 3 | 4 | 5 | 60 | P/A | Define `RequestConfig` dataclass with typed fields. Provider-specific extras via `extra: dict` |

**Assembly RPN Summary:** 4 failure modes, 1 critical (RPN ≥ 100), highest RPN = 100

---

## Summary: Top 20 Critical Failure Modes (RPN ≥ 100)

| Rank | ID | Assembly | Failure Mode | RPN | Category |
|------|-----|----------|-------------|-----|----------|
| 1 | E-02 | Execution | Streaming failure mid-stream — no fallback | 336 | E/F |
| 2 | X-07 | Resilience | Streaming has no resilience at all | 280 | E/F/M |
| 3 | P-04 | Provider Mgmt | No provider capability metadata | 245 | C/L |
| 4 | R-08 | Routing | No context-length awareness in routing | 210 | B/C |
| 5 | Q-02 | Request Proc | No token estimation — can't prevent oversized requests | 210 | B/C |
| 6 | O-01 | Observability | No logging — all failures are silent | 210 | N |
| 7 | R-02 | Routing | Exhausted provider skipped with no feedback | 196 | N |
| 8 | R-06 | Routing | No capability-based routing | 196 | C/L |
| 9 | R-10 | Routing | Shared usage state across threads | 196 | J/M |
| 10 | S-03 | State Mgmt | No file locking — concurrent corruption | 168 | H/M |
| 11 | SEC-01 | Security | API keys could be logged in error messages | 168 | I |
| 12 | SEC-03 | Security | No prompt injection protection | 168 | I |
| 13 | E-01 | Execution | No timeout on API calls | 160 | E/J |
| 14 | S-08 | State Mgmt | No token accounting — only request counts | 160 | K |
| 15 | R-03 | Routing | All providers exhausted → no recovery guidance | 140 | M |
| 16 | R-04 | Routing | Forced provider doesn't check exhaustion | 150 | C |
| 17 | R-05 | Routing | Model name not validated against provider | 180 | C |
| 18 | E-03 | Execution | Usage counted before stream completes | 175 | K |
| 19 | X-01 | Resilience | Only 3 exception types caught | 175 | D/E/M |
| 20 | X-03 | Resilience | No circuit breaker — keeps trying dead providers | 150 | M |

---

## Failure Category Distribution (16 buckets)

| Category | Count | % | Description |
|----------|-------|---|-------------|
| C — Routing | 12 | 14% | Wrong provider/model selected, stale routing |
| F — Response | 10 | 12% | Malformed/truncated output, missing data |
| E — Execution | 10 | 12% | Timeout, retry storm, streaming interruption |
| M — Reliability | 9 | 11% | Circuit breaker stuck, retry never stops |
| N — Observability | 8 | 9% | Missing logs, silent failures |
| K — Cost/Quota | 7 | 8% | Quota exhausted, wrong accounting |
| O — Configuration | 7 | 8% | Bad env vars, stale config |
| D — Provider | 7 | 8% | Offline, throttled, invalid key |
| L — Compatibility | 6 | 7% | API change, capability mismatch |
| J — Performance | 5 | 6% | High latency, memory exhaustion |
| A — Input | 5 | 6% | Invalid prompt, oversized request |
| H — State | 4 | 5% | Conversation lost, cache corruption |
| I — Security | 4 | 5% | Key leakage, prompt injection |
| B — Context | 3 | 3% | Token overflow, missing history |
| P — Extensibility | 3 | 3% | Plugin crash, adapter mismatch |
| G — Tool | 0 | 0% | No tool calling implemented yet |

**Total identified failure modes: 87**

---

## Recommended Fix Priority

### Phase 1: Critical Safety (fix before any production use)

1. **E-01** — Add timeout to OpenAI client (1-line fix)
2. **X-01** — Catch broader exception types (1-line fix)
3. **E-02 / X-07** — Add error handling inside `_stream()` generator
4. **SEC-01** — Sanitize API keys from error messages
5. **F-01** — Bounds check on `response.choices[0]`
6. **E-03** — Fix usage increment timing for streaming

### Phase 2: Core Reliability (fix before relying on it daily)

7. **O-01** — Add logging
8. **R-08 / Q-02** — Add token estimation + context-length filtering
9. **X-03** — Add circuit breaker for dead providers
10. **R-02** — Log when providers are skipped
11. **S-03** — Add file locking for usage file
12. **X-02** — Add retry within provider before fallback

### Phase 3: Capability Awareness (fix for quality of life)

13. **P-04 / R-06** — Add capability metadata to providers
14. **C-03** — Return structured response object with metadata
15. **S-08 / F-08** — Track token usage, not just request counts
16. **R-07** — Quota-aware routing (sort by remaining quota)
17. **C-01** — Add async interface
18. **CFG-01 / CFG-02** — External config file for providers

### Phase 4: Production Hardening (fix for shared/long-term use)

19. **EXT-02** — Middleware system
20. **EXT-03** — Pluggable routing strategies
21. **C-06** — OpenAI-compatible server mode
22. **R-09** — Auto-discover models from provider APIs
23. **S-06** — Session/conversation management
24. **SEC-03** — Prompt injection mitigations

---

## Appendix: What We Have vs. What We Need

| Capability | Current State | Target State |
|-----------|--------------|-------------|
| Provider routing | Static priority | Health + quota + latency aware |
| Fallback | Linear, no retry | Retry + circuit breaker + backoff |
| Streaming | No error handling | Error recovery + clean cancellation |
| Usage tracking | Request count only | Token count + cost + latency |
| Error handling | 3 exception types | All OpenAI exceptions + categorized |
| Logging | None | Structured, per-request tracing |
| Config | Hardcoded in source | YAML file + env overrides |
| Response | Bare string | Structured object with metadata |
| Async | Not supported | Full async support |
| Capabilities | Not tracked | Per-provider capability database |
| Token estimation | None | tiktoken-based estimation |
| Context awareness | None | Filter providers by context window |
| Security | .env + .gitignore | Key sanitization + prompt guards |
| Extensibility | providers param + kwargs | Plugin interface + middleware |
