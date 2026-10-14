# MuK AI Compatible Providers

One generic **OpenAI Compatible** provider for the AI Assistant: OpenRouter
(shipped pre-configured), DeepInfra, vLLM, Ollama, opencode and every other
endpoint speaking the OpenAI Chat Completions wire.

## Setup

1. Install this module, then open **AI Assistant > Configuration > Providers**.
2. OpenRouter is already there: paste the API key and click **Test Connection**.
3. For anything else, duplicate the **OpenAI Compatible** template (or create a
   provider of type **OpenAI Compatible**), set the **Custom URL** to the
   endpoint base URL (e.g. `https://api.deepinfra.com/v1/openai`,
   `http://localhost:11434/v1`), then **Fetch Models**.
4. **Fetch Models** adds the endpoint catalogue as chat models and picks the
   first as default; **Refresh Models** additionally archives what is gone.
   Models can still be added by hand.

## Extra headers

Some gateways need extra HTTP headers: `HTTP-Referer` / `X-Title` on
OpenRouter, `x-opencode-session` on opencode. Set them as a JSON object in
**Extra Headers**, e.g. `{"HTTP-Referer": "https://example.com", "X-Title":
"AI Assistant"}`. The API key stays optional so keyless local endpoints work.
