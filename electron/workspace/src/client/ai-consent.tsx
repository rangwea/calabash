/** Trusted host UI only. Never mounted inside a tool iframe. */
import { useEffect, useRef, useState } from 'react'
import type { AIPending, AIModel, AIReview } from '../types.ts'
import { rememberedModel, rememberModel } from './ai-model-choice.ts'
import css from './ai-consent.module.css'
interface API {
  pending(): Promise<AIPending[]>; models(): Promise<AIModel[]>;
  review(worker: string, request: string, model: string): Promise<AIReview>;
  approve(id: string): Promise<void>; reject(worker: string, request: string): Promise<void>; cancel(id: string): Promise<void>;
}
export function AIConsent({api,t}: {api:API;t:(zh:string,en:string)=>string}) {
  const [pending,setPending]=useState<AIPending[]>([]), [models,setModels]=useState<AIModel[]>([])
  const [model,setModel]=useState(''), [review,setReview]=useState<AIReview|null>(null)
  const [busy,setBusy]=useState(false), [sending,setSending]=useState(''), [notice,setNotice]=useState(''), [preparing,setPreparing]=useState(false)
  const [retry,setRetry]=useState(0)
  const selected=useRef('')
  useEffect(()=>{
    let disposed=false,loading=false
    const update=async()=>{
      if(loading)return;loading=true
      try {
        const requests=await api.pending();if(disposed)return;setPending(requests)
        if(requests.length){
          const values=await api.models();if(disposed)return;setModels(values)
          if(!values.some(value=>value.key===selected.current)){
            let restored='';try{restored=rememberedModel(localStorage,values)}catch{/* Storage disabled. */}
            selected.current=restored;setModel(restored)
          }
        }
      }catch{/* Read-only poll retries; never submit automatically. */}finally{loading=false}
    }
    void update();const timer=setInterval(()=>void update(),1000)
    return()=>{disposed=true;clearInterval(timer)}
  },[api])
  const first=pending[0],worker=first?.worker_id,request=first?.request_id,digest=first?.digest
  useEffect(()=>{
    let disposed=false;setReview(null)
    if(!worker||!request||!model||sending){setPreparing(false);return}
    setPreparing(true);setNotice('')
    void api.review(worker,request,model).then(value=>{if(!disposed)setReview(value)},()=>{if(!disposed)setNotice(t('暂时无法准备确认，请重试。','Unable to prepare confirmation. Please retry.'))}).finally(()=>{if(!disposed)setPreparing(false)})
    return()=>{disposed=true}
  },[api,worker,request,digest,model,sending,retry])
  const fail=()=>setNotice(t('本次操作未完成，请检查请求或模型连接后手动重试。','The operation did not complete. Check the request or model connection, then retry manually.'))
  const choose=(key:string)=>{
    selected.current=key;setModel(key);setReview(null)
    const value=models.find(value=>value.key===key)
    if(value)try{rememberModel(localStorage,value)}catch{/* Memory-only choice. */}
  }
  const reject=async(p:AIPending)=>{setBusy(true);try{await api.reject(p.worker_id,p.request_id);setReview(null);setPending(values=>values.filter(value=>value.request_id!==p.request_id))}catch{fail()}finally{setBusy(false)}}
  const approve=async()=>{
    if(!review||sending||review.model.key!==model||review.pending.request_id!==request||review.pending.digest!==digest)return
    const id=review.id;setSending(id);setPending(values=>values.filter(value=>value.request_id!==review.pending.request_id));setReview(null);setNotice('')
    try{await api.approve(id)}catch{fail()}finally{setSending('')}
  }
  if(!pending.length&&!sending&&!notice)return null
  return <aside className={css.card} aria-label={t('AI 处理确认','AI processing confirmation')}>
    {sending?<><strong role="status">{t('AI 正在处理','AI is processing')}</strong><p>{t('结果会显示在工具中，你可以继续使用其他页面。','Results will appear in the tool. You can continue using other pages.')}</p><button className={css.button} onClick={()=>{void api.cancel(sending).catch(fail)}}>{t('停止','Stop')}</button></>:first?<>
      <header className={css.header}><strong>{first.title}</strong><span className={css.source}>{first.name}</span></header>
      <label className={css.model}>{t('使用模型','Model')}<select aria-label={t('选择模型','Choose a model')} value={model} disabled={busy} onChange={e=>choose(e.target.value)}><option value="">{t('请选择模型','Choose a model')}</option>{models.map(value=><option key={value.key} value={value.key}>{value.label}</option>)}</select></label>
      {!models.length&&<p>{t('请先在设置中配置可用模型。','Configure an available model in settings first.')}</p>}
      <p>{t('将发送你提供的内容；外部模型会将内容发送至对应服务。','Your supplied content will be sent; external models send it to their service.')}</p>
      <details key={`${worker}:${request}:${model}`} className={css.details}><summary>{t('查看发送内容','View content to send')} · {first.characters} {t('字','characters')}</summary>{review?<><pre>{review.text}</pre><details><summary>{t('处理要求','Processing instructions')}</summary><pre>{review.instruction}</pre></details></>:<p role="status">{preparing?t('正在准备…','Preparing…'):t('请选择模型以查看内容。','Choose a model to view content.')}</p>}</details>
      <p className={css.hint}>{t('不附加聊天、其他文件或日志。每次发送都需确认。','No chat, other files or logs are added. Every submission requires confirmation.')}</p>
      <footer className={css.actions}><button className={css.button} disabled={busy} onClick={()=>void reject(first)}>{t('取消','Cancel')}</button><button className={`${css.button} ${css.primary}`} disabled={busy||preparing||!review||review.model.key!==model||review.pending.digest!==digest} onClick={()=>void approve()}>{preparing?t('正在准备…','Preparing…'):t('确认处理','Confirm and process')}</button></footer>
      {pending.length>1&&<p className={css.hint}>{t('还有其他请求等待确认','More requests are awaiting confirmation')} · {pending.length-1}</p>}
    </>:null}
    {notice&&<div role="status"><p>{notice}</p>{first&&<button className={css.button} disabled={preparing||busy} onClick={()=>setRetry(value=>value+1)}>{t('重试','Retry')}</button>}<button className={css.button} onClick={()=>setNotice('')}>{t('关闭提示','Dismiss')}</button></div>}
  </aside>
}
