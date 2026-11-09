"""Small office tools consume the same generated Action types as user tools."""
import json


def fixture(kind):
    action = 'office.excel.process' if kind == 'excel' else 'office.word.fill_template'
    parameters = '{input_ids: files.map(file => file.id), deduplicate_by: ["编号"]}' if kind == 'excel' else '{template_id: files[0]!.id, values: {客户: "合成客户", 编号: "001"}}'
    return {
        'tool.json': json.dumps({'format': 'calabash-react-tool', 'version': 1, 'project': 'demo', 'name': 'office_' + kind, 'title': 'Office acceptance'}),
        'backend/main.py': 'def setup(app, sdk):\n    pass\n',
        'frontend/App.tsx': '''import {useState} from 'react'
import {Alert, Button} from 'antd'
import {officeActions, CalabashFiles, CalabashResults, CalabashJobStatus, type ToolFile} from '@calabash/ui'
export default function App() {
  const [files,setFiles]=useState<ToolFile[]>([])
  const [pending,setPending]=useState(false), [error,setError]=useState('')
  async function submit() {
    if (pending || !files.length) return
    setPending(true); setError('')
    try { await officeActions.start(''' + json.dumps(action) + ', ' + parameters + ''') }
    catch { setError('暂时无法处理，请重试') }
    finally { setPending(false) }
  }
  return <main className="office-tool"><h1>Office acceptance</h1>
    <CalabashFiles onChange={setFiles}/>
    {error && <Alert type="error" title={error}/>}
    <Button type="primary" loading={pending} disabled={!files.length} onClick={()=>void submit()}>处理</Button>
    <CalabashJobStatus/><CalabashResults/>
  </main>
}''',
    }
