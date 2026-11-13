import { useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Form, Input, Typography } from 'antd'
import { api } from '@calabash/api'
export default function App() {
  const [text, setText] = useState('你好'), [message, setMessage] = useState('')
  const [error, setError] = useState(''), [pending, setPending] = useState(false)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let disposed = false
    const controller = new AbortController()
    void api.read_message({ signal: controller.signal }).then(result => {
      if (!disposed) setMessage(result.message)
    }).catch(() => {
      if (!disposed) setError('暂时无法读取已保存的内容，请重新打开工具')
    }).finally(() => { if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort() }
  }, [])
  async function submit() {
    if (loading || pending || !text.trim()) return
    setPending(true); setError('')
    try { const result = await api.create_message({ body: { text: text.trim() } }); setMessage(result.message) }
    catch { setError('暂时无法完成，请重试或让 AI 帮你修复') }
    finally { setPending(false) }
  }
  return <main style={{ display: 'grid', gap: 16, padding: 24, minWidth: 0 }}>
    <header><Typography.Title level={3}>办公工具</Typography.Title><Typography.Text type="secondary">内容保存在本机，重新打开后可查看。</Typography.Text></header>
    {error && <Alert type="error" title={error} showIcon />}
    <Card><Form layout="vertical" onFinish={() => { void submit() }}><Form.Item label="内容"><Input value={text} maxLength={200} disabled={loading || pending} onChange={event => setText(event.target.value)} /></Form.Item><Button htmlType="submit" type="primary" loading={pending} disabled={loading || !text.trim()}>确认</Button></Form></Card>
    {message ? <Card><p role="status">{message}</p></Card> : <Empty description="还没有结果" />}
  </main>
}
