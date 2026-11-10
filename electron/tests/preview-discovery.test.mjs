import assert from 'node:assert/strict'
import {PreviewDiscovery} from '../workspace/src/client/preview-discovery.ts'
const gate=new PreviewDiscovery()
assert.equal(gate.ready(null,false,false),false)
assert.equal(gate.ready('passed-current',false,true),false)
assert.equal(gate.ready('passed-current',false,false),true,'no clock or second sample is required')
assert.equal(gate.ready('passed-current',false,false),false,'do not replay an accepted attempt')
assert.equal(gate.ready('passed-repair',true,false),false,'preserve an opened iframe')
assert.equal(gate.ready('passed-repair',false,false),true)
const other=new PreviewDiscovery()
assert.equal(other.ready('passed-current',false,false),true,'independent session')
console.log('PASS: passed revision launches immediately once, no quiet-period polling, opened frames preserved')
