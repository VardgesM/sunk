import type { Rule, RuleValue } from '../../types/automation';
import type { Tag } from '../../types/configuration';

export const conditionModes = { ALL: 'All conditions must match', ANY: 'Any condition may match' };
export const operatorLabels = { '>': 'Greater than', '>=': 'At least', '<': 'Less than', '<=': 'At most', '==': 'Equal to', '!=': 'Not equal to' };
const states: Record<string, string> = {
  IDLE: 'Waiting for conditions', WAITING_FOR_DURATION: 'Waiting for the condition duration',
  ACTIVE: 'Rule is active; see execution result', COOLDOWN: 'Waiting for the cooldown to end',
  DISABLED: 'Rule is disabled', ERROR: 'Rule needs attention',
};
const results: Record<string, string> = {
  SUCCESS: 'Last execution succeeded', FAILED: 'Last execution failed',
  PARTIAL_FAILURE: 'Some commands failed', COMMANDS_CREATED: 'Commands created; awaiting results',
  TRIGGERED: 'Rule triggered', SKIPPED: 'Execution skipped',
};

export const stateExplanation = (state: string) => states[state] ?? 'Reported runtime state';
export const resultExplanation = (result: string) => results[result] ?? 'Reported execution result';
export const tagName = (id: number, tags: Map<number, Tag>) => tags.get(id)?.name ?? `Tag #${id} (name unavailable)`;
export function displayValue(value: RuleValue | null, unit?: string | null): string {
  if (value === null) return 'Unavailable';
  if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
  // Numeric values remain decimal strings, including integers beyond JS safe precision.
  return `${value}${unit ? ` ${unit}` : ''}`;
}
export function conditionSummary(id: number, operator: string, value: RuleValue, tags: Map<number, Tag>): string {
  const op = typeof value === 'boolean' ? operator === '==' ? 'is' : operator === '!=' ? 'is not' : operator : operator;
  return `${tagName(id, tags)} ${op} ${displayValue(value, tags.get(id)?.unit)}`;
}
export function reportedCondition(rule: Rule): string | null {
  if (!rule.enabled || !rule.runtime || ['ERROR', 'DISABLED'].includes(rule.runtime.state)) return null;
  return typeof rule.runtime.condition_state === 'boolean' ? rule.runtime.condition_state ? 'Matched (TRUE)' : 'Not matched (FALSE)' : null;
}
export const displayTime = (timestamp: string | null | undefined) => timestamp ? new Date(timestamp).toLocaleString() : 'Never';
