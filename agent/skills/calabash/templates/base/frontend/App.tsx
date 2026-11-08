import { useState } from 'react'
import { Alert, Button, Card, Empty, Form, Input, Typography } from 'antd'
import { api } from '@calabash/api'
export default function App() {
  const [text, setText] = useState('你好'), [message, setMessage] = useState('')
  const [error, setError] = useState(''), [pending, setPending] = useState(false)
  async function submit() {
    if (pending || !text.trim()) return
    setPending(true); setError('')
    try { const result = await api.create_message({ body: { text: text.trim() } }); setMessage(result.message) }
    catch { setError('暂时无法完成，请重试或让 AI 帮你修复') }
    finally { setPending(false) }
  }
  return <main style={{ display: 'grid', gap: 16, padding: 24, minWidth: 0 }}>
    <header><Typography.Title level={3}>办公工具</Typography.Title><Typography.Text type="secondary">输入内容，开始使用。</Typography.Text></header>
    {error && <Alert type="error" title={error} showIcon />}
    <Card><Form layout="vertical" onFinish={() => { void submit() }}><Form.Item label="内容"><Input value={text} maxLength={200} disabled={pending} onChange={event => setText(event.target.value)} /></Form.Item><Button htmlType="submit" type="primary" loading={pending} disabled={!text.trim()}>确认</Button></Form></Card>
    {message ? <Card><p role="status">{message}</p></Card> : <Empty description="还没有结果" />}
  </main>
}
