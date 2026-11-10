/** Bounded plain-data result reader. No HTML/Markdown execution or arbitrary URLs. */
export async function readAIResult(response:Response):Promise<string> {
  if(!response.ok||!response.body)throw new Error('Result unavailable')
  const reader=response.body.getReader(),chunks:Uint8Array[]=[]
  let length=0
  try{
    while(true){
      const {done,value}=await reader.read();if(done)break
      length+=value.byteLength;if(length>65536)throw new Error('Result too large')
      chunks.push(value)
    }
    const bytes=new Uint8Array(length);let offset=0
    for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength}
    return new TextDecoder('utf-8',{fatal:true}).decode(bytes)
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
}
export function resultFields(text:string):Array<[string,string]> {
  try{
    const value:unknown=JSON.parse(text)
    if(!value||typeof value!=='object'||Array.isArray(value))return []
    const entries=Object.entries(value)
    if(entries.length>20||entries.some(([,item])=>!['string','number','boolean'].includes(typeof item)))return []
    return entries.map(([key,value])=>[key,String(value)])
  }catch{return []}
}
