"""LeadGenPlatform-only provider configuration. Secrets never enter status responses or repr."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re


ENV_FILE = Path(__file__).resolve().parent.parent / '.env'
_MODEL_NAME = re.compile(r'^gemini-[a-zA-Z0-9_.-]{1,100}$')
_NAMES = {
    'LEADGEN_GEMINI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY',
    'LEADGEN_GEMINI_MODEL', 'GEMINI_MODEL', 'LEADGEN_GEMINI_FALLBACK_MODELS',
}


def _settings():
    """Read only this app's opt-in configuration, with environment precedence."""
    values = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith('export '):
                line = line[7:]
            name, separator, value = line.partition('=')
            name = name.strip()
            if separator and name in _NAMES:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                else:
                    value = value.split(' #', 1)[0].strip()
                values[name] = value
    for name in _NAMES:
        if name in os.environ:
            values[name] = os.environ[name]
    return values


@dataclass(frozen=True)
class LiveConfig:
    api_key: str = field(default='', repr=False)
    models: tuple[str, ...] = ('gemini-3.8-flash', 'gemini-3.5-flash')
    timeout_seconds: float = 90.0
    max_candidates: int = 6
    max_model_calls: int = 5
    max_pages: int = 8
    max_sources: int = 18

    @classmethod
    def from_environment(cls):
        values = _settings()
        key = next((values[name].strip() for name in ('LEADGEN_GEMINI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY') if values.get(name, '').strip()), '')
        primary = values.get('LEADGEN_GEMINI_MODEL') or values.get('GEMINI_MODEL') or 'gemini-3.8-flash'
        fallback = values.get('LEADGEN_GEMINI_FALLBACK_MODELS', 'gemini-3.5-flash')
        names = tuple(dict.fromkeys(name.strip() for name in (primary, *fallback.split(',')) if name.strip()))
        if not names or any(not _MODEL_NAME.fullmatch(name) for name in names):
            # A static error avoids echoing a malformed setting, which might be a secret.
            raise ValueError('Set LEADGEN_GEMINI_MODEL to a Gemini model ID, such as gemini-3.8-flash.')
        return cls(api_key=key, models=names[:3])


def get_live_status():
    try:
        config = LiveConfig.from_environment()
    except (ValueError, OSError):
        return {'configured': False, 'provider': 'gemini', 'models': [], 'model': None, 'limits': {}, 'error': 'LeadGenPlatform provider configuration is invalid. Check the local .env file.'}
    return {
        'configured': bool(config.api_key), 'provider': 'gemini',
        'model': config.models[0], 'models': list(config.models),
        'limits': {'max_candidates': config.max_candidates, 'max_model_calls': config.max_model_calls,
                   'max_pages': config.max_pages, 'timeout_seconds': config.timeout_seconds,
                   'search_requests': 1},
    }
