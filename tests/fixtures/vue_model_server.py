"""Local scripted model for packaged Vue acceptance. Never calls real providers."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path('/private/tmp/calabash-vue-acceptance-model')
TARGET = {'project': 'demo', 'name': 'counter'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        packet = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages = packet['messages']
        start = max(i for i, item in enumerate(messages) if item['role'] == 'user')
        task = messages[start]['content']
        results = [item for item in messages[start + 1:] if item['role'] == 'tool']
        index = len(results)
        args = None
        if '修复' in task:
            if index == 0:
                name, args = 'read_tool', TARGET
            elif index == 1:
                name, args = 'read_tool_file', {**TARGET, 'path': 'frontend/App.vue'}
            elif index == 2:
                name, args = 'read_tool_logs', TARGET
            elif index == 3:
                name, args = 'inspect_preview', TARGET
            elif index == 4:
                inspected = json.loads(results[-1]['content'])
                assert inspected.get('untrusted_events'), inspected
                source = json.loads(results[0]['content'])
                name, args = 'patch_tool_file', {**TARGET, 'path': 'frontend/App.vue', 'old': "console.error('Synthetic broken action')", 'new': 'count.value++', 'revision': source['revision']}
            elif index == 5:
                name, args = 'validate_tool', TARGET
            final = '修改已保存；保留原界面。请手动刷新预览、重新授权并验收。尚未运行验证。'
        else:
            if index == 0:
                name, args = 'inspect_preview', TARGET
            elif index == 1:
                page = json.loads(results[-1]['content'])['untrusted_page']
                element = next(item for item in page['elements'] if item['label'] == 'Increment')
                name, args = 'interact_preview', {**TARGET, 'element_id': element['id'], 'action': 'click', 'reason': '合成验收：将计数从 0 改为 1，不写入业务文件。'}
            elif index == 2:
                name, args = 'verify_preview', {**TARGET, 'checks': [{'kind': 'text_visible', 'text': 'Count: 1'}, {'kind': 'no_frontend_errors'}]}
            else:
                checked = json.loads(results[-1]['content'])
                assert checked['status'] == 'checks_passed', checked
            final = '两项指定检查通过：Count: 1 可见，当前页面没有记录前端错误。未验证其他业务。'
        with (ROOT / 'requests.jsonl').open('a') as output:
            output.write(json.dumps({'step': index, 'tool': name if args is not None else None}) + '\n')
        delta = {'content': final} if args is None else {'tool_calls': [{'index': 0, 'id': f'qa-{index}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
        body = {'choices': [{'delta': delta, 'finish_reason': 'stop' if args is None else 'tool_calls'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}
        encoded = ('data: ' + json.dumps(body) + '\n\ndata: [DONE]\n\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    (ROOT / 'port').write_text(str(server.server_port))
    print(server.server_port, flush=True)
    server.serve_forever()
