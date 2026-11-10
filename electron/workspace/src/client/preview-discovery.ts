/** A passed current revision triggers once; no quiet period, polling or refresh. */
export class PreviewDiscovery {
  private attempted=new Set<string>()
  ready(revision:string|null, opened:boolean, busy:boolean):boolean {
    if(!revision||opened||busy||this.attempted.has(revision))return false
    this.attempted.add(revision)
    if(this.attempted.size>16)this.attempted.delete(this.attempted.values().next().value!)
    return true
  }
}
