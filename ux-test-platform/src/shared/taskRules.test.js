import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluateCompletionRule, normalizeCompletionRule } from './taskRules.js';

test('normalizeCompletionRule keeps supported non-empty rules', () => {
  assert.deepEqual(
    normalizeCompletionRule({ type: 'url_contains', value: ' /checkout ' }),
    { type: 'url_contains', value: '/checkout' }
  );
});

test('normalizeCompletionRule falls back to manual for missing or unsupported rules', () => {
  assert.deepEqual(normalizeCompletionRule({ type: 'unknown', value: 'x' }), { type: 'manual', value: '' });
  assert.deepEqual(normalizeCompletionRule({ type: 'text_contains', value: '   ' }), { type: 'manual', value: '' });
  assert.deepEqual(normalizeCompletionRule(null), { type: 'manual', value: '' });
});

test('evaluateCompletionRule matches URL fragments', () => {
  const result = evaluateCompletionRule(
    { type: 'url_contains', value: '/checkout/success' },
    { url: 'https://shop.test/checkout/success?order=1' }
  );
  assert.equal(result.matched, true);
  assert.deepEqual(result.rule, { type: 'url_contains', value: '/checkout/success' });
});

test('evaluateCompletionRule matches selectors and reports invalid selectors', () => {
  const matched = evaluateCompletionRule(
    { type: 'selector_exists', value: '#done' },
    { querySelector: (selector) => selector === '#done' }
  );
  assert.equal(matched.matched, true);

  const invalid = evaluateCompletionRule(
    { type: 'selector_exists', value: '[' },
    {
      querySelector: () => {
        throw new Error('invalid selector');
      },
    }
  );
  assert.equal(invalid.matched, false);
  assert.equal(invalid.error.message, 'invalid selector');
});

test('evaluateCompletionRule matches page text case-insensitively', () => {
  const result = evaluateCompletionRule(
    { type: 'text_contains', value: 'ORDER CONFIRMED' },
    { text: 'Your order confirmed page is ready.' }
  );
  assert.equal(result.matched, true);
});
