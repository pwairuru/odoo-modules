from __future__ import annotations

from odoo.addons.muk_ai.providers import REGISTRY

from .compat import (
    DeepInfraProvider,
    OpencodeProvider,
    OpenAICompatProvider,
    OpenRouterProvider,
    SiliconFlowProvider,
)


for _provider in (
    OpenAICompatProvider,
    OpenRouterProvider,
    OpencodeProvider,
    DeepInfraProvider,
    SiliconFlowProvider,
):
    REGISTRY[_provider.name] = _provider
