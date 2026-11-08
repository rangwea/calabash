import assert from 'node:assert/strict'
import {setTimeout as delay} from 'node:timers/promises'
import {createConnectionMonitor} from '../desktop-ui/src/runtime_connection.mjs'

const deferred = () => {let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}

// Switching tools cancels old probes and ignores late results.
const first=deferred(), second=deferred(), states=[], signals=[]
const monitor=createConnectionMonitor((resource, options)=>{
  signals.push(options.signal)
  return resource==='/first'?first.promise:second.promise
}, value=>states.push(value),10000)
monitor.start('/first','http://127.0.0.1:1111/')
monitor.start('/second','http://127.0.0.1:2222/')
assert(signals[0].aborted)
first.resolve({state:'unavailable',running:false})
await delay(0)
assert.equal(states.length,0)
second.resolve({state:'ready',running:true,origin:'http://127.0.0.1:2222'})
await delay(0)
assert.equal(states[0].state,'ready')
monitor.stop()
assert(signals[1].aborted)

// Poll failures only change host feedback; they never invoke a restart/mutation.
let calls=0
const failures=[]
const offline=createConnectionMonitor(async(resource,options)=>{
  assert.equal(resource,'/runtime')
  assert.equal(options.method,undefined)
  calls++
  throw new Error('offline')
},value=>failures.push(value),2)
offline.start('/runtime','http://127.0.0.1:3333/')
await delay(25)
offline.stop()
assert(calls>=2)
assert.equal(failures[0].state,'unknown')
const count=calls
await delay(10)
assert.equal(calls,count)

// A replaced worker must not make the stale iframe look healthy.
const replaced=[]
const replacement=createConnectionMonitor(async()=>({state:'ready',running:false,origin:'http://127.0.0.1:5555'}),value=>replaced.push(value),10000)
replacement.start('/runtime','http://127.0.0.1:4444/')
await delay(0)
replacement.stop()
assert.equal(replaced[0].state,'unavailable')
console.log('Runtime monitoring ignores stale probes, stops cleanly and never restarts tools automatically')
