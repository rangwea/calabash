/** Host projections contain no source, host token, logs or model credentials. */
export interface ToolTarget { project: string; name: string }
export interface ToolEntry extends ToolTarget { title?: string; description?: string; revision?: string }
export interface Preview extends ToolTarget { url: string; revision: string }
export interface AgentArguments { action_id?: string; reference?: string; component?: string; property_name?: string; project?: string; name?: string; path?: string; content?: string; old?: string; new?: string; offset?: number; limit?: number }

export interface UIPreset { id: string; version: number; title: string; mention: string; description: string; color: string; aliases?: string[]; title_en?: string; description_en?: string }
