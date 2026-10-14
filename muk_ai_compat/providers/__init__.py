from __future__ import annotations

from odoo.addons.muk_ai.providers import REGISTRY

from .compat import OpenAICompatProvider


REGISTRY[OpenAICompatProvider.name] = OpenAICompatProvider
