from . import chatgpt, claude, gemini, grok

SPECS = {module.SPEC.name: module.SPEC for module in (grok, chatgpt, claude, gemini)}
