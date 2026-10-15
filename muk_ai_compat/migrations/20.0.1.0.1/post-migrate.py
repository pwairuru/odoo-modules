from __future__ import annotations

from odoo import SUPERUSER_ID, api
from odoo.sql_db import Cursor

#: ``(legacy code, provider type)`` of the shipped presets, once stored as
#: generic ``openai_compat`` accounts and now first-class provider types.
RENAMED = (
    ('openrouter', 'openrouter'),
    ('opencode', 'opencode'),
    ('deepinfra', 'deepinfra'),
    ('siliconflow', 'siliconflow'),
)


def migrate(cr: Cursor, version: str) -> None:
    """Rename the shipped generic accounts to their provider types.

    Models move with their account; company defaults follow; a leftover
    legacy row is removed once empty. User-made ``openai_compat`` accounts
    (custom codes) are untouched.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Providers = env['muk_ai.provider']
    for code, name in RENAMED:
        legacy = Providers.search(
            [('name', '=', 'openai_compat'), ('code', '=', code)]
        )
        if not legacy:
            continue
        target = Providers.search(
            [('name', '=', name), ('id', 'not in', legacy.ids)], limit=1
        )
        if not target:
            legacy.write({'name': name, 'code': 'default'})
            continue
        source = legacy[0]
        env['muk_ai.model'].search(
            [('provider_id', 'in', legacy.ids)]
        ).write({'provider_id': target.id})
        env['res.company'].search(
            [('default_ai_provider_id', 'in', legacy.ids)]
        ).write({'default_ai_provider_id': target.id})
        for field in (
            'api_key',
            'api_url',
            'api_headers',
            'default_chat_model_id',
            'default_image_model_id',
        ):
            if not target[field] and source[field]:
                target[field] = source[field]
        cr.execute('DELETE FROM muk_ai_provider WHERE id IN %s', (tuple(legacy.ids),))
