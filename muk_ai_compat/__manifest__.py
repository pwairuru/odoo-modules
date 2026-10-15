{
    'name': 'MuK AI Compatible Providers',
    'summary': 'OpenAI-compatible LLM providers (OpenRouter, DeepInfra, Ollama) for the AI Assistant',
    'description': """
        Adds a generic OpenAI-compatible provider to muk_ai, so one account
        type serves OpenRouter, DeepInfra, vLLM, Ollama, opencode and every
        other endpoint speaking the OpenAI Chat Completions wire - no new
        addon per vendor. Ships OpenRouter pre-configured, fetches the model
        catalogue from the endpoint's ``/models`` (add missing, or replace
        and archive what is gone), and carries per-provider extra HTTP
        headers for gateways that need them (``HTTP-Referer`` / ``X-Title``
        on OpenRouter, ``x-opencode-session`` on opencode). The API key stays
        optional, so keyless local endpoints work too.
    """,
    'version': '20.0.1.0.1',
    'category': 'Productivity',
    'license': 'LGPL-3',
    'author': 'MuK IT',
    'website': 'http://www.mukit.at',
    'depends': [
        'muk_ai',
    ],
    'data': [
        'data/provider.xml',
        'views/provider.xml',
        'views/res_config_settings.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
