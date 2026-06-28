"""Prompt templates — conventions

This directory contains Jinja2 templates used as LLM system/user prompts.
Edit `.md` files without recompiling Python.

## Structure

```
prompts/
├── README.md           # this file
├── architect/
│   └── system.md       # Architect agent system prompt
├── writer/
│   └── system.md       # Writer agent system prompt
├── reviewer/
│   └── system.md       # Reviewer agent system prompt
├── assessment/
│   └── system.md       # Assessment agent system prompt
└── router/
    └── system_*.md     # Various router endpoint prompts
```

## Conventions

### Template name → file path
Use `<agent>/<purpose>.md`. Reference in code as:
```python
get_renderer().render("architect/system.md")
```

### Variables
Use `{{ var_name }}`. Variables are auto-escaped by default. If you need
raw rendering (e.g., trusted JSON), use `{{ var | safe }}` — but only
when the variable is fully server-controlled.

### Conditionals
```jinja
{% if language == "kk" %}
Қазақстандық корпоративтік тренинг мысалдарын қосыңыз.
{% endif %}
```

### Loops
```jinja
Learning objectives:
{% for obj in learning_objectives %}
- {{ obj }}
{% endfor %}
```

### Template inheritance
```jinja
{% extends "base_architect.md" %}
{% block examples %}
{% if industry == "legal" %}
... юридические примеры ...
{% endif %}
{% endblock %}
```

## Security: prompt injection

User-supplied content (course titles, lesson text, uploaded documents) is
auto-escaped. Markup special characters (`<`, `>`, `&`, `"`, `'`) become
HTML entities. This is the first line of defense against prompt injection.

Jinja2 directives passed as variables are NOT re-interpreted. If a user
inputs `{{ evil_directive }}` as a course title, it appears literally in
the prompt, not as a new template directive.

## Testing

Every template MUST have a corresponding test in `apps/api/tests/test_renderer.py`:
1. Golden output test (key sections present)
2. Variable substitution test
3. Conditional block test (where applicable)

## Adding a new prompt

1. Create the `.md` file in the appropriate `<agent>/` directory
2. Add it to the agent's Python file via `get_renderer().render(...)`
3. Add tests in `apps/api/tests/test_renderer.py`
4. Document any new variables in this README