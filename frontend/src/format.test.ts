import { describe, expect, it } from 'vitest'
import { expectedPoints, fixtureLabel, money, signed, sourceLabel } from './format'

describe('decision-room formatting', () => {
  it('formats FPL tenths as pounds', () => expect(money(15)).toBe('£1.5m'))
  it('keeps positive comparison signs visible', () => expect(signed(2.34)).toBe('+2.3'))
  it('marks fixture venue', () => expect(fixtureLabel('Hull City', true)).toBe('Hull City (H)'))
  it('formats expected points consistently', () => expect(expectedPoints(5.24)).toBe('5.2 xP'))
  it('shows missing expected points honestly', () => expect(expectedPoints(null)).toBe('—'))
  it('translates internal source names', () => expect(sourceLabel('fdr_recent_xg_fallback')).toBe('Fallback'))
})
