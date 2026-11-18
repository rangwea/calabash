/** The packager owns native paths; tests must not guess macOS or Windows layout. */
import {readFileSync} from 'node:fs'
import {spawnSync} from 'node:child_process'
const layout=JSON.parse(readFileSync(new URL('../dist/electron/package-layout.json',import.meta.url),'utf8'))
const result=spawnSync(process.execPath,['electron/tests/ai-roundtrip.mjs'],{stdio:'inherit',env:{...process.env,CALABASH_INSTALLED_APP:layout.app}})
if(result.error) throw result.error
process.exitCode=result.status??1
