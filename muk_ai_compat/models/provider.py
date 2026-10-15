from __future__ import annotations

import json

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AIProvider(models.Model):
    """Extra headers and model catalogue fetch for OpenAI-compatible accounts."""

    _inherit = 'muk_ai.provider'

    # ----------------------------------------------------------
    # Fields
    # ----------------------------------------------------------

    api_headers = fields.Text(
        string='Extra Headers',
        help=(
            'JSON object of extra HTTP headers sent with every request of '
            'this provider, e.g. {"HTTP-Referer": "https://example.com", '
            '"X-Title": "AI Assistant"} for OpenRouter or '
            '{"x-opencode-session": "my-session"} for opencode.'
        ),
        groups='base.group_system',
        default='{}',
    )

    # ----------------------------------------------------------
    # Helper
    # ----------------------------------------------------------

    def _extra_headers(self) -> dict:
        """Return the parsed extra headers, empty when unset or invalid."""
        try:
            headers = json.loads(self.sudo().api_headers or '{}')
        except ValueError:
            return {}
        if not isinstance(headers, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in headers.items()
            if value is not None
        }

    def _fetch_remote_models(self) -> list[dict]:
        """Return the model entries the endpoint lists at ``GET /models``.

        :raise UserError: on a transport error, an error status, or a payload
            without a model list
        """
        client = self._get_client()
        url = f'{client.api_url}/models'
        try:
            response = client._http_session().get(
                url,
                headers=client.headers(),
                timeout=self.request_timeout,
            )
            response.raise_for_status()
        except requests.HTTPError as error:
            client._raise(client._error_details(error))
        except requests.RequestException as error:
            client._raise(error)
        try:
            payload = response.json()
        except ValueError:
            client._raise(
                self.env._(
                    'endpoint did not return JSON - check the Custom URL: it '
                    'must be the API base URL (usually ending in /v1), not a '
                    'web page.'
                )
            )
        entries = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            client._raise(
                self.env._(
                    'endpoint returned no model list - check the Custom URL: '
                    'it must be the API base URL (usually ending in /v1).'
                )
            )
        return [entry for entry in entries if isinstance(entry, dict)]

    # ----------------------------------------------------------
    # Actions
    # ----------------------------------------------------------

    def action_fetch_models(self) -> dict:
        """Fetch the endpoint catalogue into ``muk_ai.model``, then notify.

        Entries missing locally are created as chat models; archived ones
        come back. With the ``fetch_replace`` context flag, active models no
        longer listed are archived instead of kept.
        """
        self.ensure_one()
        from odoo.addons.muk_ai_compat.providers.compat import OpenAICompatProvider

        if not isinstance(self._get_client(), OpenAICompatProvider):
            raise UserError(
                self.env._(
                    'Model fetch is only available on OpenAI Compatible providers.'
                )
            )
        replace = bool(self.env.context.get('fetch_replace'))
        entries = {
            entry.get('id'): entry
            for entry in self._fetch_remote_models()
            if entry.get('id')
        }
        Model = self.env['muk_ai.model']
        known = {
            record.technical_name: record
            for record in Model.search([('provider_id', '=', self.id)])
        }
        created, restored = 0, 0
        for technical_name in sorted(entries):
            entry = entries[technical_name]
            context_window = (
                entry.get('context_length')
                or entry.get('context_window')
                or entry.get('max_context_length')
                or 128000
            )
            if technical_name in known:
                record = known[technical_name]
                if not record.active:
                    record.active = True
                    restored += 1
            else:
                Model.create(
                    {
                        'name': technical_name,
                        'provider_id': self.id,
                        'technical_name': technical_name,
                        'modality': 'chat',
                        'context_window': context_window,
                        'input_rate': 0.0,
                        'output_rate': 0.0,
                    }
                )
                created += 1
        archived = 0
        if replace:
            for technical_name, record in known.items():
                if record.active and technical_name not in entries:
                    record.active = False
                    archived += 1
        if not self.default_chat_model_id and entries:
            first = Model.search(
                [
                    ('provider_id', '=', self.id),
                    ('technical_name', '=', sorted(entries)[0]),
                    ('modality', '=', 'chat'),
                ],
                limit=1,
            )
            self.default_chat_model_id = first
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._('AI Provider'),
                'message': self.env._(
                    'Fetched %(count)s models (%(created)s new, '
                    '%(restored)s restored, %(archived)s archived).',
                    count=len(entries),
                    created=created,
                    restored=restored,
                    archived=archived,
                ),
                'sticky': False,
            },
        }

    # ----------------------------------------------------------
    # Constraints
    # ----------------------------------------------------------

    @api.constrains('api_headers')
    def _check_api_headers(self) -> None:
        """Reject extra headers that are not a JSON object of strings.

        :raise ValidationError: when the value is not a JSON object mapping
            header names to their values
        """
        for record in self:
            if not record.api_headers:
                continue
            try:
                headers = json.loads(record.api_headers)
            except ValueError:
                raise ValidationError(
                    self.env._('Extra Headers must be a valid JSON object.')
                )
            if not isinstance(headers, dict) or not all(
                isinstance(key, str) and isinstance(value, (str, int, float))
                for key, value in headers.items()
            ):
                raise ValidationError(
                    self.env._(
                        'Extra Headers must be a JSON object mapping header '
                        'names to their values.'
                    )
                )
