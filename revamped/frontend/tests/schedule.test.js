import { test } from 'node:test'
import assert from 'node:assert/strict'
import { distance, reorderSchedule, restoreOrder } from '../utils/schedule.js'

const row = (id, platform, start, lat = 4) => ({ Well_ID: id, Platform_Assigned: platform, Start_Day: start, End_Day: start + 7, Duration_Days: 5, Mob_Demob_Days: 2, BOPD: 500, Cost_kUSD: 84, Lat: lat, Lon: 112 })
const original = [row('A', 'P1', 0), row('B', 'P1', 10, 5), row('C', 'P1', 21), row('D', 'P2', 0)]

test('moving a well recalculates dates and transit while preserving saved results', () => {
  const saved = JSON.stringify(original)
  const rows = reorderSchedule(original, 'C', 'A', '2026-12-30')
  assert.deepEqual(rows.map(r => r.Well_ID), ['C', 'A', 'B', 'D'])
  assert.equal(rows[0].Start_Date, '2026-12-30')
  assert.equal(rows[0].End_Date, '2027-01-06')
  assert.equal(rows[1].Start_Day, 8) // Same location still requires one transit day.
  assert.equal(rows[2].Start_Day, rows[1].End_Day + Math.ceil(distance(rows[1], rows[2]) / 50) + 1)
  assert.equal(rows[2].Transit_Dist_km, 111.2)
  assert.equal(rows[2].Cost_kUSD, 84)
  assert.equal(JSON.stringify(original), saved)
  assert.equal(rows[3], original[3])
})

test('drop after a target and restore saved order produce identical schedules', () => {
  const rows = reorderSchedule(original, 'A', 'C', '2026-10-28', true)
  const restored = restoreOrder(original, rows.map(r => r.Well_ID), '2026-10-28')
  assert.deepEqual(rows.filter(r => r.Platform_Assigned === 'P1'), restored.filter(r => r.Platform_Assigned === 'P1'))
  assert.deepEqual(rows.map(r => r.Well_ID), ['B', 'C', 'A', 'D'])
})

test('invalid moves and stale drafts are rejected without mutating the source', () => {
  assert.throws(() => reorderSchedule(original, 'A', 'D', '2026-10-28'), /same platform/)
  assert.throws(() => restoreOrder(original, ['A', 'B'], '2026-10-28'), /does not match/)
  const long = original.map(r => ({ ...r, Duration_Days: 180 }))
  const saved = JSON.stringify(long)
  assert.throws(() => reorderSchedule(long, 'C', 'A', '2026-10-28'), /365-day/)
  assert.equal(JSON.stringify(long), saved)
})
