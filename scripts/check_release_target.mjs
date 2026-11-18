/** Refuse cross-architecture runtimes and tags that do not describe this checkout. */
import {readFileSync} from 'node:fs'
const target=`${process.platform==='darwin'?'mac':process.platform==='win32'?'win':process.platform}-${process.arch}`
if(target!==process.env.EXPECTED_TARGET) throw new Error(`Expected native ${process.env.EXPECTED_TARGET}, got ${target}`)
const version=JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8')).version
if(process.env.GITHUB_REF_TYPE==='tag' && process.env.GITHUB_REF_NAME!==`v${version}`) throw new Error(`Release tag must be v${version}`)
console.log(`Native ${target}; Calabash ${version}`)
