"""Generate the built-in TS action client from canonical Pydantic schemas."""
import json

from service.actions import registry
from service.actions.models import ActionResult, ActionRun, ActionSubmission


def frontend_source():
    declarations = {}
    def render(schema):
        if '$ref' in schema:
            return 'Office' + schema['$ref'].rsplit('/', 1)[1]
        if 'enum' in schema:
            return '(' + ' | '.join(json.dumps(value) for value in schema['enum']) + ')'
        if 'const' in schema:
            return json.dumps(schema['const'])
        if 'anyOf' in schema:
            return '(' + ' | '.join(render(item) for item in schema['anyOf']) + ')'
        kind = schema.get('type')
        if kind == 'array':
            return 'Array<' + render(schema['items']) + '>'
        if kind == 'object':
            if 'properties' not in schema:
                return 'Record<string, ' + render(schema.get('additionalProperties', {'type': 'string'})) + '>'
            required = set(schema.get('required', []))
            return '{ ' + '; '.join(json.dumps(key) + ('' if key in required else '?') + ': ' + render(value) for key, value in schema['properties'].items()) + ' }'
        if kind in {'integer', 'number'}:
            return 'number'
        if kind in {'string', 'boolean', 'null'}:
            return kind
        raise ValueError('Unsupported built-in action schema')
    def declare(model):
        schema = model.model_json_schema()
        for name, value in schema.get('$defs', {}).items():
            declarations[name] = render(value)
        declarations[model.__name__] = render(schema)
    for model in (ActionResult, ActionRun, ActionSubmission):
        declare(model)
    actions = registry.catalog()['actions']
    for item in actions:
        declare(registry.get(item['id']).parameters)
    lines = ['// Generated from built-in Pydantic contracts. Never edit generated types.']
    lines += ['export type Office' + name + ' = ' + value for name, value in declarations.items()]
    lines += ['export interface OfficeInputs {']
    lines += [json.dumps(item['id']) + ': Office' + registry.get(item['id']).parameters.__name__ for item in actions]
    lines += ['}', '''export const officeActions = {
  start: <K extends keyof OfficeInputs>(action: K, parameters: OfficeInputs[NoInfer<K>]): Promise<OfficeActionSubmission> => request('/actions/' + encodeURIComponent(action), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({protocol_version: 1, action_version: 1, parameters})
  }),
  runs: (): Promise<Array<OfficeActionRun>> => request('/action-runs'),
}''']
    return '\n'.join(lines) + '\n'
