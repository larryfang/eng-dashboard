import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildProviderCards,
  buildProviderRows,
  formatDuration,
  formatSettingsTimestamp,
  getSchedulerSectionStatusLabel,
  getSyncRunMeta,
  getSyncRunStats,
} from '../src/features/settings/settingsHelpers.js'

test('buildProviderCards derives health states from validation and live status', () => {
  const cards = buildProviderCards({
    validation: {
      gitlab: { ok: true, user: 'gauss', error: null },
      jira: { ok: false, user: null, error: '401' },
      port: null,
      email: { ok: true, user: 'Digest Bot <digest@example.com>', error: null, provider: 'mailgun' },
    },
    gitlabHealth: {
      status: 'ok',
      authenticated_as: 'gauss-live',
      error: null,
    },
    portStatus: {
      configured: true,
      connected: false,
      error: 'timeout',
      token_expires_at: null,
    },
  })

  assert.deepEqual(cards, [
    {
      label: 'GitLab API',
      ok: true,
      detail: 'gauss-live',
      error: null,
    },
    {
      label: 'Jira API',
      ok: false,
      detail: 'Run validation to confirm Jira access',
      error: '401',
    },
    {
      label: 'Port.io',
      ok: false,
      detail: 'Configured for service catalog sync',
      error: 'timeout',
    },
    {
      label: 'Email delivery',
      ok: true,
      detail: 'Digest Bot <digest@example.com>',
      error: null,
    },
  ])
})

test('buildProviderRows returns export-safe scalar values', () => {
  assert.deepEqual(
    buildProviderRows([
      { label: 'GitLab API', ok: true, detail: 'gauss', error: null },
      { label: 'Port.io', ok: false, detail: 'Not configured', error: 'missing secret' },
      { label: 'Email delivery', ok: false, detail: 'Not configured', error: 'missing provider' },
    ]),
    [
      { provider: 'GitLab API', ok: 'yes', detail: 'gauss', error: '' },
      { provider: 'Port.io', ok: 'no', detail: 'Not configured', error: 'missing secret' },
      { provider: 'Email delivery', ok: 'no', detail: 'Not configured', error: 'missing provider' },
    ],
  )
})

test('sync helpers format duration and status labels', () => {
  assert.equal(formatDuration(undefined), '—')
  assert.equal(formatDuration(42.2), '42s')
  assert.equal(formatDuration(150), '2.5m')
  assert.equal(getSchedulerSectionStatusLabel({ status: 'success', is_active: true }), 'running')
  assert.equal(getSchedulerSectionStatusLabel({ status: 'error', is_active: false }), 'error')
})

test('sync history helpers expose metadata and stats for the audit trail', () => {
  assert.equal(formatSettingsTimestamp(null), 'Not yet synced')
  assert.notEqual(formatSettingsTimestamp('2026-03-06T12:00:00Z'), 'Not yet synced')
  assert.match(
    getSyncRunMeta({
      trigger_source: 'manual',
      period_days: 30,
      started_at: '2026-03-06T12:00:00Z',
    }),
    /^manual · 30d · started /,
  )
  assert.deepEqual(
    getSyncRunStats({ records_synced: 18, duration_seconds: 61 }),
    { records: '18 records', duration: '1.0m' },
  )
})
