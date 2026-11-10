/** Remember identity only. Catalog keys and consent are deliberately never persisted. */
import type { AIModel } from '../types.ts'
interface Storage { getItem(key:string):string|null; setItem(key:string,value:string):void }
const key='calabash.ai.model-choice'
export function rememberedModel(storage:Storage, models:AIModel[]):string {
  try {
    const value:unknown=JSON.parse(storage.getItem(key)||'null')
    if(!value||typeof value!=='object'||!('provider' in value)||!('model' in value))return ''
    return models.find(model=>model.provider===value.provider&&model.model===value.model)?.key||''
  }catch{return ''}
}
export function rememberModel(storage:Storage, model:AIModel):void {
  try{storage.setItem(key,JSON.stringify({provider:model.provider,model:model.model}))}catch{/* Memory selection still works when storage is unavailable. */}
}
