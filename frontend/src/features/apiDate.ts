// Timestamps from the API. The backend stores naive UTC (SQLite DateTime columns)
// and sends it with no zone: "2026-11-10T01:00:00". `new Date()` reads such a
// string as LOCAL time, so every relative time was off by the UTC offset
// (11 hours in Melbourne). A value that states its zone is kept as it is.
const HAS_ZONE = /(Z|[+-]\d{2}(:?\d{2})?)$/i
const HAS_TIME = /\d{2}:\d{2}/

export function parseApiDate(value: string): Date {
  const text = value.trim().replace(' ', 'T')
  if (!HAS_TIME.test(text) || HAS_ZONE.test(text)) return new Date(text)
  return new Date(`${text}Z`)
}
