export const TASK_COMPLETION_RULE_TYPES = new Set([
  'url_contains',
  'selector_exists',
  'text_contains',
]);

export const normalizeCompletionRule = (rule) => {
  const type = typeof rule?.type === 'string' ? rule.type : 'manual';
  const value = typeof rule?.value === 'string' ? rule.value.trim() : '';
  if (!TASK_COMPLETION_RULE_TYPES.has(type) || !value) {
    return { type: 'manual', value: '' };
  }
  return { type, value };
};

export const evaluateCompletionRule = (rule, page) => {
  const normalizedRule = normalizeCompletionRule(rule);
  if (normalizedRule.type === 'manual') {
    return { matched: false, rule: normalizedRule };
  }

  if (normalizedRule.type === 'url_contains') {
    return {
      matched: String(page?.url || '').includes(normalizedRule.value),
      rule: normalizedRule,
    };
  }

  if (normalizedRule.type === 'selector_exists') {
    try {
      return {
        matched: Boolean(page?.querySelector?.(normalizedRule.value)),
        rule: normalizedRule,
      };
    } catch (error) {
      return {
        matched: false,
        rule: normalizedRule,
        error,
      };
    }
  }

  const pageText = String(page?.text || '').toLowerCase();
  return {
    matched: pageText.includes(normalizedRule.value.toLowerCase()),
    rule: normalizedRule,
  };
};
