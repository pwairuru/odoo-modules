from __future__ import annotations

import json
from collections.abc import Callable

from odoo.addons.muk_ai.providers.base import ProviderBase
from odoo.addons.muk_ai.providers.region import CUSTOM


class OpenAICompatProvider(ProviderBase):
    """OpenAI-compatible Chat Completions adapter with extra header support.

    One account type for OpenRouter, DeepInfra, vLLM, Ollama, opencode and
    every other endpoint speaking the ``/chat/completions`` wire. The API key
    is optional so keyless local endpoints serve too; per-provider extra
    headers cover the gateways that need them.
    """

    name = 'openai_compat'
    label = 'OpenAI Compatible'
    default_model = ''
    default_url = ''
    regions = (CUSTOM,)

    supports_web_search = False
    supports_code_interpreter = False

    reasoning_error_tokens = ()

    # ----------------------------------------------------------
    # Properties
    # ----------------------------------------------------------

    @property
    def authenticated(self) -> bool:
        """Return ``True`` even without a key: local endpoints need none."""
        return True

    @property
    def api_url(self) -> str:
        """Return the custom base URL without a trailing slash."""
        return super().api_url.rstrip('/')

    # ----------------------------------------------------------
    # Functions
    # ----------------------------------------------------------

    def headers(self) -> dict:
        """Return the JSON headers, bearer only when a key is set, extras merged."""
        headers = {'Content-Type': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'
        headers.update(self.provider._extra_headers())
        return headers

    def serves_builtin_tools(self, model: str) -> bool:
        """Return ``False``: this wire sends function tools only."""
        return False

    def request(
        self,
        inputs: list[dict],
        tools_schema: list[dict] | None = None,
        text_schema: dict | None = None,
        on_delta: Callable | None = None,
        model: str | None = None,
        enable_web_search: bool = False,
        enable_code_interpreter: bool = False,
        cache_key: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        """Build and stream a Chat Completions request.

        Reasoning effort and built-in search/code flags are ignored: most
        compatible endpoints take neither, and silently sending them breaks
        the strict ones.
        """
        model = self.model_for(model)
        body = {
            'model': model,
            'messages': self._inputs_to_messages(inputs),
            'stream': True,
            'stream_options': {'include_usage': True},
        }
        if max_tokens := self.provider.max_tokens:
            body['max_tokens'] = max_tokens
        if text_schema:
            body['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': text_schema.get('name', 'response'),
                    'schema': text_schema['schema'],
                    'strict': True,
                },
            }
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': name,
                    'description': description,
                    'parameters': parameters,
                },
            }
            for name, description, parameters in self._unique_tools(tools_schema)
        ]
        if tools:
            body['tools'] = tools
        return self._stream(body, on_delta)

    # ----------------------------------------------------------
    # Helper
    # ----------------------------------------------------------

    @classmethod
    def _inputs_to_messages(cls, inputs) -> list[dict]:
        """Convert canonical inputs into Chat Completions messages.

        Carried tool calls re-attach to their assistant message, tool outputs
        become ``tool`` messages; system items lead as one system message.
        """
        messages = []
        if system_text := cls._system_text(inputs):
            messages.append(
                {'role': 'system', 'content': [{'type': 'text', 'text': system_text}]}
            )
        for item in cls._wire_items(inputs):
            if item.get('type') == 'function_call':
                arguments = item.get('arguments')
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments or {}, default=str)
                call = {
                    'id': item.get('call_id'),
                    'type': 'function',
                    'function': {
                        'name': item.get('name'),
                        'arguments': arguments,
                    },
                }
                if messages and messages[-1].get('role') == 'assistant':
                    messages[-1].setdefault('tool_calls', []).append(call)
                else:
                    messages.append(
                        {'role': 'assistant', 'content': [], 'tool_calls': [call]}
                    )
            elif item.get('type') == 'function_call_output':
                output = item.get('output')
                if not isinstance(output, str):
                    output = json.dumps(output, default=str)
                messages.append(
                    {
                        'role': 'tool',
                        'tool_call_id': item.get('call_id'),
                        'content': output or '',
                    }
                )
            elif item.get('role') in ('user', 'assistant'):
                for part in cls._content_parts(item.get('content')):
                    cls._append_turn(messages, 'content', item['role'], part)
        return messages

    @staticmethod
    def _text_part(text: str) -> dict:
        """Return the chat content part carrying a text."""
        return {'type': 'text', 'text': text}

    @classmethod
    def _attachment_part(cls, block: dict) -> dict:
        """Convert an attachment block into an image_url or text part."""
        if block.get('strategy') == 'image':
            mimetype = block.get('mimetype') or 'application/octet-stream'
            data = f'data:{mimetype};base64,{block.get("data_b64", "")}'
            return {'type': 'image_url', 'image_url': {'url': data}}
        return {'type': 'text', 'text': cls._attachment_text(block)}

    def _handle_tool_delta(
        self, chunk: dict, calls: dict, on_delta: Callable | None
    ) -> None:
        """Fold one streamed tool-call delta into ``calls``, forwarding deltas."""
        index = chunk.get('index', 0)
        entry = calls.setdefault(
            index, {'call_id': None, 'name': '', 'arguments': ''}
        )
        function = chunk.get('function') or {}
        if chunk.get('id'):
            entry['call_id'] = chunk['id']
        if function.get('name') and not entry['name']:
            entry['name'] = function['name']
            if not entry['call_id']:
                entry['call_id'] = f'call_{index}'
            self._call_on_delta(
                on_delta,
                'tool_start',
                {'call_id': entry['call_id'], 'name': entry['name']},
            )
        if args := function.get('arguments'):
            entry['arguments'] += args
            self._call_on_delta(
                on_delta,
                'tool_args',
                {'call_id': entry['call_id'] or f'call_{index}', 'delta': args},
            )

    def _stream(self, body: dict, on_delta: Callable | None) -> dict:
        """Stream a Chat Completions request, forwarding deltas, and assemble its result."""
        text, calls, usage = [], {}, {}
        truncated = False
        for event in self._post_stream('/chat/completions', body):
            if event.get('error'):
                self._raise_stream_error(event['error'], 'code', 'type')
            for choice in event.get('choices') or []:
                delta = choice.get('delta') or {}
                if content := delta.get('content'):
                    text.append(content)
                    self._call_on_delta(on_delta, 'text', {'delta': content})
                if reasoning := delta.get('reasoning_content'):
                    self._call_on_delta(on_delta, 'reasoning', {'delta': reasoning})
                for call in delta.get('tool_calls') or []:
                    self._handle_tool_delta(call, calls, on_delta)
                if (choice.get('finish_reason') or '') == 'length':
                    truncated = True
            if event.get('usage'):
                usage = event['usage']
        result_text = ''.join(text).strip()
        tool_calls = [
            self._tool_call(
                entry.get('call_id') or f'call_{index}',
                entry.get('name'),
                entry.get('arguments'),
            )
            for index, entry in calls.items()
        ]
        carry = (
            [
                {
                    'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': result_text}],
                }
            ]
            if result_text
            else []
        )
        carry += [self._call_item(call) for call in tool_calls]
        return self._result(
            result_text,
            tool_calls,
            carry,
            self._usage(
                input_tokens=(usage.get('prompt_tokens') or usage.get('input_tokens')),
                output_tokens=(
                    usage.get('completion_tokens') or usage.get('output_tokens')
                ),
            ),
            on_delta,
            truncated,
            self.provider.max_tokens or None,
        )


class OpenRouterProvider(OpenAICompatProvider):
    """OpenRouter gateway on the OpenAI-compatible wire."""

    name = 'openrouter'
    label = 'OpenRouter'


class OpencodeProvider(OpenAICompatProvider):
    """opencode gateway on the OpenAI-compatible wire."""

    name = 'opencode'
    label = 'opencode'


class DeepInfraProvider(OpenAICompatProvider):
    """DeepInfra serverless inference on the OpenAI-compatible wire."""

    name = 'deepinfra'
    label = 'DeepInfra'


class SiliconFlowProvider(OpenAICompatProvider):
    """SiliconFlow inference on the OpenAI-compatible wire."""

    name = 'siliconflow'
    label = 'SiliconFlow'
