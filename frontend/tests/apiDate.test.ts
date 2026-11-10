import assert from 'node:assert/strict'
import test from 'node:test'

import { parseApiDate } from '../src/features/apiDate.js'

test('a timestamp with no zone from the API is UTC, not local time', () => {
  // The backend stores naive UTC and sends "2026-11-10T01:00:00". `new Date()` reads
  // that as LOCAL time, so in Melbourne a 26-minute-old sync showed "11 hours ago".
  assert.equal(parseApiDate('2026-11-10T01:00:00').toISOString(), '2026-11-10T01:00:00.000Z')
  assert.equal(parseApiDate('2026-11-10 01:00:00.123456').toISOString(), '2026-11-10T01:00:00.123Z')
})

test('a timestamp that states its zone is kept', () => {
  assert.equal(parseApiDate('2026-11-10T01:00:00Z').toISOString(), '2026-11-10T01:00:00.000Z')
  assert.equal(parseApiDate('2026-11-10T12:00:00+11:00').toISOString(), '2026-11-10T01:00:00.000Z')
  assert.equal(parseApiDate('2026-11-10T01:00:00-0500').toISOString(), '2026-11-10T06:00:00.000Z')
})

test('a date with no time stays a calendar date', () => {
  assert.equal(parseApiDate('2026-11-10').toISOString(), '2026-11-10T00:00:00.000Z')
})
