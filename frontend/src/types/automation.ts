export type RuleValue = string | boolean;
export interface Condition { tag_id: number; operator: '>' | '>=' | '<' | '<=' | '==' | '!='; value: RuleValue; hysteresis: string; sort_order: number }
export interface Action { target_tag_id: number; kind: 'SET_TAG_VALUE'; value: RuleValue; sort_order: number }
export interface RuleInput { name: string; description: string | null; enabled: boolean; priority: number; condition_mode: 'ALL' | 'ANY'; for_duration_ms: number | null; cooldown_ms: number | null; conditions: Condition[]; actions: Action[] }
export interface RuleRuntime { state: string; condition_state: boolean; true_since: string | null; last_triggered_at: string | null; cooldown_until: string | null; last_result: string | null; error: string | null }
export interface Rule extends RuleInput { id: number; created_at: string; updated_at: string; runtime: RuleRuntime | null }
export interface Execution { id: number; rule_id: number; triggered_at: string; completed_at: string | null; snapshot: { tag_id: number; operator: string; comparison: RuleValue; value: RuleValue | null; quality: string }[]; result: string; error: string | null; command_ids: number[] }
