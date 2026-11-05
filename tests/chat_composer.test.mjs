import assert from 'node:assert/strict'
import {shouldSend} from '../desktop-ui/src/composer.mjs'
const enter = {key:'Enter',keyCode:13,shiftKey:false,repeat:false,isComposing:false}
const idle = {composing:false,uploading:false}
for(const event of [{...enter,isComposing:true},{...enter,keyCode:229},{...enter,shiftKey:true},{...enter,repeat:true}]) assert.equal(shouldSend(event,idle,100),false)
assert.equal(shouldSend(enter,{...idle,composing:true},100),false)
assert.equal(shouldSend(enter,{...idle,uploading:true},100),false)
assert.equal(shouldSend(enter,{...idle,ended:100},125),false)
assert.equal(shouldSend(enter,{...idle,ended:100},200),true)
assert.equal(shouldSend(enter,idle,100),true)
console.log('Vue composer IME, repeat and uploading guards passed')
