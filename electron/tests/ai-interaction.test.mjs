/** Synthetic preference/data tests: no browser profile, credentials or provider. */
import assert from 'node:assert/strict'
import {rememberModel, rememberedModel} from '../workspace/src/client/ai-model-choice.ts'
import {readAIResult, resultFields} from '../../scripts/tool_ai_result.ts'
let stored=null
const storage={getItem:()=>stored,setItem:(_,value)=>{stored=value}}
const models=[{key:'catalog-generation-1',label:'Synthetic',provider:'synthetic',model:'local'}]
assert.equal(rememberedModel(storage,models),'')
rememberModel(storage,models[0])
assert.deepEqual(JSON.parse(stored),{provider:'synthetic',model:'local'})
assert.equal(rememberedModel(storage,[{...models[0],key:'generation-2'}]),'generation-2')
assert.equal(rememberedModel(storage,[]),'')
stored='broken';assert.equal(rememberedModel(storage,models),'')
const unavailable={getItem(){throw Error('disabled')},setItem(){throw Error('disabled')}}
rememberModel(unavailable,models[0]);assert.equal(rememberedModel(unavailable,models),'')
const text='<img src=x onerror=alert(1)>\n中文📄'
assert.equal(await readAIResult(new Response(text)),text)
assert.deepEqual(resultFields('{"label":"客户咨询"}'),[['label','客户咨询']])
assert.deepEqual(resultFields('{"name":"<script>data only</script>","amount":12,"valid":true}'),[['name','<script>data only</script>'],['amount','12'],['valid','true']])
assert.deepEqual(resultFields('{"nested":{"x":1}}'),[])
assert.deepEqual(resultFields('null'),[])
assert.deepEqual(resultFields('broken'),[])
await assert.rejects(readAIResult(new Response('x'.repeat(65537))),/large/)
await assert.rejects(readAIResult(new Response(new Uint8Array([0xff]))))
await assert.rejects(readAIResult(new Response('unavailable',{status:404})))
console.log('PASS: model identity only, catalog generation changes, unavailable storage; bounded UTF-8 text and scalar result display')
