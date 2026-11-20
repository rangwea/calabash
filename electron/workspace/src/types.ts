/** Host projections contain no source, host token, logs or model credentials. */
export interface ToolTarget { project: string; name: string }
export interface ToolEntry extends ToolTarget { title?: string; description?: string; revision?: string }
export interface Preview extends ToolTarget { url: string; revision: string }
export interface AgentArguments { action_id?: string; reference?: string; component?: string; property_name?: string; project?: string; name?: string; path?: string; content?: string; old?: string; new?: string; offset?: number; limit?: number }

export interface UIPreset { id: string; version: number; title: string; mention: string; description: string; color: string; aliases?: string[]; title_en?: string; description_en?: string }

/** Safe host-only consent view; contains proposed text only after a user opens review. */
export interface AIPending { worker_id:string; request_id:string; invocation_id:string; revision:string; digest:string; expires:number; task:string; title:string; characters:number; state:'pending'|'running'; project:string; name:string }
export interface AIModel { key:string; label:string; provider:string; model:string }
export interface AIReview { id:string; pending:AIPending; text:string; instruction:string; model:AIModel }

export interface ActionSummary { id: string; title: string; title_en: string; description: string; description_en: string }
