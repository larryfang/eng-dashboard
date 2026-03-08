import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDigestPayload,
  buildSavedViewPayload,
  createDefaultDigestDraft,
  formatReportTimestamp,
  getDigestRunMeta,
  getDigestRunTitle,
  getDigestScheduleLabel,
  parseDigestRecipients,
} from '../src/features/reports/reportingHelpers.js'

test('createDefaultDigestDraft returns the expected defaults', () => {
  assert.deepEqual(createDefaultDigestDraft(), {
    name: 'Weekly Executive Digest',
    recipients: '',
    frequency: 'weekly',
    weekday: 0,
    hour_utc: 8,
  })
})

test('buildSavedViewPayload trims the name and ignores blank values', () => {
  assert.equal(buildSavedViewPayload('   ', true), null)
  assert.deepEqual(buildSavedViewPayload(' Leadership View ', false), {
    name: 'Leadership View',
    view_type: 'executive_report',
    config: {
      include_pulse: false,
      format: 'html',
    },
  })
})

test('parseDigestRecipients trims and drops empty items', () => {
  assert.deepEqual(
    parseDigestRecipients('a@example.com, , b@example.com  ,c@example.com'),
    ['a@example.com', 'b@example.com', 'c@example.com'],
  )
})

test('buildDigestPayload shapes weekly digests and normalizes hour and weekday', () => {
  const payload = buildDigestPayload(
    {
      name: ' Weekly Ops ',
      recipients: 'lead@example.com, vp@example.com',
      frequency: 'weekly',
      weekday: 99,
      hour_utc: 40,
    },
    { selectedViewId: 7, includePulse: true },
  )

  assert.deepEqual(payload, {
    name: 'Weekly Ops',
    saved_view_id: 7,
    recipients: ['lead@example.com', 'vp@example.com'],
    include_pulse: true,
    frequency: 'weekly',
    weekday: 6,
    hour_utc: 23,
    active: true,
  })
})

test('buildDigestPayload clears weekday for daily digests and rejects blank names', () => {
  assert.equal(
    buildDigestPayload(
      {
        name: '   ',
        recipients: '',
        frequency: 'daily',
        weekday: 4,
        hour_utc: 8,
      },
      { selectedViewId: undefined, includePulse: false },
    ),
    null,
  )

  assert.deepEqual(
    buildDigestPayload(
      {
        name: 'Daily digest',
        recipients: '',
        frequency: 'daily',
        weekday: 4,
        hour_utc: -3,
      },
      { selectedViewId: undefined, includePulse: false },
    ),
    {
      name: 'Daily digest',
      saved_view_id: null,
      recipients: [],
      include_pulse: false,
      frequency: 'daily',
      weekday: null,
      hour_utc: 0,
      active: true,
    },
  )
})

test('reporting labels expose digest schedule and run metadata', () => {
  assert.equal(
    getDigestScheduleLabel({ frequency: 'weekly', hour_utc: 8, weekday: 2 }),
    'weekly at 08:00 UTC · weekday 2',
  )
  assert.equal(
    getDigestRunTitle({ id: 14, subject: null }),
    'Digest run #14',
  )
  assert.match(
    getDigestRunMeta({
      generated_at: '2026-03-06T12:00:00Z',
      delivery_state: 'sent',
      recipient_count: 3,
    }),
    /sent · 3 recipients$/,
  )
})

test('formatReportTimestamp falls back when there is no value', () => {
  assert.equal(formatReportTimestamp(null), '—')
  assert.notEqual(formatReportTimestamp('2026-03-06T12:00:00Z'), '—')
})
