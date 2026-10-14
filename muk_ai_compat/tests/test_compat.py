from __future__ import annotations

from unittest.mock import patch

import requests

from odoo.exceptions import UserError, ValidationError

from odoo.addons.muk_ai.tests.common import AITestCommon, json_response, sse_response
from odoo.addons.muk_ai.tests.providers import (
    FILE_TEXT,
    TEXT_FILE,
    TOOLS,
    USER,
    ProviderCase,
    ProviderTestCase,
    _attached,
    _usage,
    deltas_of,
)
from odoo.addons.muk_ai.tests.test_providers import TestProviders


def chunk(
    content: str | None = None,
    reasoning: str | None = None,
    calls: list | None = None,
    finish: str | None = None,
    usage: dict | None = None,
) -> dict:
    """Build one Chat Completions stream chunk."""
    delta = {}
    if content:
        delta['content'] = content
    if reasoning:
        delta['reasoning_content'] = reasoning
    if calls:
        delta['tool_calls'] = calls
    choice = {'delta': delta}
    if finish:
        choice['finish_reason'] = finish
    event = {'choices': [choice]}
    if usage is not None:
        event['usage'] = usage
    return event


def call_chunk(
    index: int,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> dict:
    """Build one streamed tool-call delta of a Chat Completions chunk."""
    function = {}
    if name:
        function['name'] = name
    if arguments:
        function['arguments'] = arguments
    part = {'index': index, 'function': function}
    if call_id:
        part['id'] = call_id
    return part


def html_response(status_code: int = 404) -> requests.Response:
    """Build an HTTP response carrying an HTML error page, like a website does."""
    response = requests.Response()
    response.status_code = status_code
    response._content = (
        b'<!DOCTYPE html><html><head></head><body>not found</body></html>'
    )
    response.headers['Content-Type'] = 'text/html'
    response.url = 'https://provider.test/'
    return response


def _compat_wire(url: str, body: dict) -> dict:
    """Normalise a Chat Completions request body."""
    tools = body.get('tools') or []
    system = ''.join(
        part.get('text') or ''
        for message in body.get('messages') or []
        if message.get('role') == 'system'
        for part in message.get('content') or []
    )
    return {
        'model': body['model'],
        'system': system,
        'tools': [tool['function']['name'] for tool in tools],
        'builtin': [],
        'max_tokens': body.get('max_tokens'),
        'effort': None,
        'schema': ((body.get('response_format') or {}).get('json_schema') or {}).get(
            'schema'
        ),
        'content': body['messages'][-1]['content'],
    }


COMPAT_CASE = ProviderCase(
    xmlid='muk_ai_compat.provider_openrouter',
    model='openrouter/auto',
    endpoint='/chat/completions',
    auth=('Authorization', 'Bearer test-key'),
    builtin=(),
    unlimited=None,
    text=[
        chunk('Hel'),
        chunk('lo'),
        chunk(finish='stop', usage={'prompt_tokens': 11, 'completion_tokens': 4}),
    ],
    usage=_usage(11, 4),
    tool_call=[
        chunk(calls=[call_chunk(0, call_id='c1', name='do_x')]),
        chunk(calls=[call_chunk(0, arguments='{"a":')]),
        chunk(calls=[call_chunk(0, arguments='1}')]),
        chunk(finish='stop'),
    ],
    reasoning=[
        chunk(reasoning='weighing it'),
        chunk('answer'),
        chunk(finish='stop'),
    ],
    truncated=[
        chunk('partial'),
        chunk(
            finish='length', usage={'prompt_tokens': 7, 'completion_tokens': 4096}
        ),
    ],
    reply={'choices': [{'message': {'content': 'ok'}}], 'usage': {}},
    error=lambda message: {'error': {'message': message}},
    wire=_compat_wire,
)

COMPAT_ATTACHMENTS = [
    (
        'image',
        _attached(strategy='image', mimetype='image/png', data_b64='AAA='),
        {
            'openai_compat': [
                {
                    'type': 'image_url',
                    'image_url': {'url': 'data:image/png;base64,AAA='},
                }
            ],
        },
    ),
    (
        'pdf',
        _attached(
            strategy='file',
            mimetype='application/pdf',
            data_b64='PDF=',
            filename='doc.pdf',
        ),
        {
            'openai_compat': [
                {'type': 'text', 'text': '--- File: doc.pdf (application/pdf) ---\n'}
            ],
        },
    ),
    (
        'text',
        _attached(**TEXT_FILE),
        {'openai_compat': [{'type': 'text', 'text': FILE_TEXT}]},
    ),
    (
        'truncated',
        _attached(**TEXT_FILE, truncated=True),
        {'openai_compat': [{'type': 'text', 'text': f'{FILE_TEXT}\n[truncated]'}]},
    ),
    (
        'plain string',
        'hi',
        {'openai_compat': [{'type': 'text', 'text': 'hi'}]},
    ),
]

COMPAT_EFFORTS = [
    ('openai_compat', 'openrouter/auto', None, None),
    ('openai_compat', 'openrouter/auto', 'low', None),
    ('openai_compat', 'openrouter/auto', 'max', None),
]


class TestCompatProviders(TestProviders):
    """Verify the Chat Completions wire honours the provider contract."""

    allow_inherited_tests_method = True
    cases = {'openai_compat': COMPAT_CASE}
    attachments = COMPAT_ATTACHMENTS
    efforts = COMPAT_EFFORTS

    # ----------------------------------------------------------
    # Setup
    # ----------------------------------------------------------

    @classmethod
    def setUpClass(cls) -> None:
        """Point the shipped OpenRouter account at the mocked endpoint."""
        super().setUpClass()
        provider = cls.providers['openai_compat']
        provider.write({'api_key': 'test-key', 'api_url': 'https://provider.test'})
        provider.default_chat_model_id = cls.env['muk_ai.model'].create(
            {
                'name': 'openrouter/auto',
                'provider_id': provider.id,
                'technical_name': 'openrouter/auto',
                'modality': 'chat',
                'context_window': 128000,
                'input_rate': 0.0,
                'output_rate': 0.0,
            }
        )

    # ----------------------------------------------------------
    # Tests
    # ----------------------------------------------------------

    def test_a_failed_request_raises_a_user_error(self):
        for name, case in self.cases.items():
            for failure, answers, message in (
                (
                    'http',
                    [json_response({'error': {'message': 'server exploded'}}, 500)],
                    'server exploded',
                ),
                (
                    'transport',
                    [requests.ConnectionError('connection refused')],
                    'connection refused',
                ),
                ('stream', [[case.error('Overloaded')]], 'Overloaded'),
            ):
                with self.subTest(provider=name, failure=failure):
                    with (
                        self._wire(*answers) as sent,
                        self.assertRaisesRegex(UserError, message),
                    ):
                        self.providers[name]._request_responses(
                            inputs=[USER], on_delta=lambda kind, data: None
                        )
                    self.assertEqual(len(sent), len(answers))

    def test_built_in_tools_follow_their_flags(self):
        for web, code in (
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ):
            with self.subTest(web=web, code=code):
                _result, _deltas, sent = self._stream(
                    'openai_compat',
                    COMPAT_CASE.text,
                    model=COMPAT_CASE.model,
                    tools_schema=TOOLS,
                    enable_web_search=web,
                    enable_code_interpreter=code,
                )
                body = sent[0]['json']
                self.assertEqual(
                    COMPAT_CASE.wire(sent[0]['url'], body)['builtin'], []
                )
                self.assertEqual(
                    COMPAT_CASE.wire(sent[0]['url'], body)['tools'], ['x']
                )
                self.assertNotIn('web_search', str(body))
                self.assertNotIn('code_interpreter', str(body))


class TestCompatProvider(AITestCommon):
    """Verify the keyless requests, extra headers and model fetch."""

    # ----------------------------------------------------------
    # Helper
    # ----------------------------------------------------------

    def _provider(self, **values):
        """Create an OpenAI Compatible account on the mocked endpoint."""
        return self.env['muk_ai.provider'].create(
            {
                'name': 'openai_compat',
                'code': 'test',
                'api_region': 'custom',
                'api_url': 'https://provider.test',
                'api_key': 'test-key',
                **values,
            }
        )

    # ----------------------------------------------------------
    # Tests
    # ----------------------------------------------------------

    def test_requests_work_without_a_key_and_merge_extra_headers(self):
        provider = self._provider(api_key=False)
        deltas = []
        with self._capture_post(
            sse_response(list(COMPAT_CASE.text)),
            sse_response(list(COMPAT_CASE.text)),
        ) as captured:
            result = provider._request_responses(
                inputs=[USER],
                on_delta=lambda kind, data: deltas.append((kind, data)),
            )
            self.assertEqual(result['text'], 'Hello')
            self.assertNotIn('Authorization', captured[0][1]['headers'])
            provider.api_headers = (
                '{"HTTP-Referer": "https://example.com", '
                '"x-opencode-session": "s1"}'
            )
            provider._request_responses(inputs=[USER])
        self.assertEqual(
            captured[1][1]['headers']['HTTP-Referer'], 'https://example.com'
        )
        self.assertEqual(captured[1][1]['headers']['x-opencode-session'], 's1')
        self.assertEqual(deltas_of(deltas, 'text'), ['Hel', 'lo'])

    def test_invalid_extra_headers_are_rejected(self):
        provider = self._provider()
        for headers in ('not json', '[1, 2]', '{"a": {"nested": true}}'):
            with self.subTest(headers=headers), self.assertRaises(ValidationError):
                provider.api_headers = headers
        provider.api_headers = '{"X-Title": "AI Assistant"}'
        provider._check_api_headers()

    def test_fetch_models_creates_and_sets_the_default(self):
        provider = self._provider()
        payload = {
            'data': [
                {'id': 'b-model'},
                {'id': 'a-model', 'context_length': 5000},
            ]
        }
        with patch.object(
            requests.Session, 'get', return_value=json_response(payload)
        ):
            action = provider.action_fetch_models()
        self.assertEqual(action['params']['type'], 'success')
        models = self.env['muk_ai.model'].search([('provider_id', '=', provider.id)])
        self.assertEqual(
            {model.technical_name for model in models}, {'a-model', 'b-model'}
        )
        self.assertEqual(
            models.filtered(lambda model: model.technical_name == 'a-model')
            .context_window,
            5000,
        )
        self.assertEqual(
            models.filtered(lambda model: model.technical_name == 'b-model')
            .context_window,
            128000,
        )
        self.assertEqual(
            provider.default_chat_model_id.technical_name, 'a-model'
        )

    def test_fetch_replace_archives_what_is_gone_and_keeps_the_rest(self):
        provider = self._provider()
        manual = self.env['muk_ai.model'].create(
            {
                'name': 'manual',
                'provider_id': provider.id,
                'technical_name': 'manual-x',
                'modality': 'chat',
                'context_window': 8000,
                'input_rate': 1.0,
                'output_rate': 1.0,
            }
        )
        payload = {'data': [{'id': 'a-model'}]}
        with patch.object(
            requests.Session, 'get', return_value=json_response(payload)
        ):
            provider.action_fetch_models()
        self.assertTrue(manual.active)
        with patch.object(
            requests.Session, 'get', return_value=json_response(payload)
        ):
            provider.with_context(fetch_replace=True).action_fetch_models()
        self.assertFalse(manual.active)
        self.assertTrue(
            self.env['muk_ai.model']
            .search(
                [
                    ('provider_id', '=', provider.id),
                    ('technical_name', '=', 'a-model'),
                ]
            )
            .active
        )

    def test_fetch_is_rejected_on_other_providers_and_on_bad_payloads(self):
        with self.assertRaisesRegex(UserError, 'only available'):
            self.provider.action_fetch_models()
        provider = self._provider()
        with (
            patch.object(
                requests.Session,
                'get',
                return_value=json_response({'error': {'message': 'nope'}}, 500),
            ),
            self.assertRaisesRegex(UserError, 'nope'),
        ):
            provider.action_fetch_models()
        with (
            patch.object(
                requests.Session, 'get', return_value=json_response({'nada': 1})
            ),
            self.assertRaisesRegex(UserError, 'no model list'),
        ):
            provider.action_fetch_models()

    def test_an_html_error_page_points_at_the_custom_url(self):
        provider = self._provider()
        with (
            self._capture_post(html_response()),
            self.assertRaisesRegex(UserError, 'HTML.*Custom URL'),
        ):
            provider._request_responses(inputs=[USER])

    def test_an_html_model_list_points_at_the_custom_url(self):
        provider = self._provider()
        with (
            patch.object(
                requests.Session, 'get', return_value=html_response(200)
            ),
            self.assertRaisesRegex(UserError, 'JSON.*Custom URL'),
        ):
            provider.action_fetch_models()

    def test_a_trailing_slash_custom_url_posts_a_single_slash(self):
        provider = self._provider(api_url='https://provider.test/')
        with self._capture_post(
            sse_response(list(COMPAT_CASE.text)),
        ) as captured:
            provider._request_responses(inputs=[USER])
        self.assertEqual(
            captured[0][0], 'https://provider.test/chat/completions'
        )

    def test_the_shipped_openrouter_account_points_at_openrouter(self):
        provider = self.env.ref('muk_ai_compat.provider_openrouter')
        self.assertEqual(provider.api_url, 'https://openrouter.ai/api/v1')
        self.assertEqual(
            provider._extra_headers()['HTTP-Referer'],
            'https://github.com/pwairuru/odoo-modules',
        )
