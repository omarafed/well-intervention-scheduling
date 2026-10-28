const day = 86400000
export function distance(a, b) {
  const rad = x => x * Math.PI / 180
  const h = Math.sin(rad(b.Lat - a.Lat) / 2) ** 2 + Math.cos(rad(a.Lat)) * Math.cos(rad(b.Lat)) * Math.sin(rad(b.Lon - a.Lon) / 2) ** 2
  return 6371 * 2 * Math.atan2(Math.sqrt(Math.min(1, h)), Math.sqrt(Math.max(0, 1 - h)))
}

// Move within a platform, retaining assignments, duration, cost and gain.
export function reorderSchedule(schedule, source, target, startDate, after = false) {
  const from = schedule.find(r => r.Well_ID === source)
  const to = schedule.find(r => r.Well_ID === target)
  if (!from || !to || from.Platform_Assigned !== to.Platform_Assigned) throw new Error('Move wells within the same platform.')
  if (source === target) return schedule
  const rows = schedule.filter(r => r.Platform_Assigned === from.Platform_Assigned).sort((a, b) => a.Start_Day - b.Start_Day).map(r => ({ ...r }))
  const moving = rows.splice(rows.findIndex(r => r.Well_ID === source), 1)[0]
  rows.splice(rows.findIndex(r => r.Well_ID === target) + (after ? 1 : 0), 0, moving)
  recalculate(rows, startDate)
  return [...schedule.filter(r => r.Platform_Assigned !== from.Platform_Assigned), ...rows].sort((a, b) => a.Platform_Assigned.localeCompare(b.Platform_Assigned) || a.Start_Day - b.Start_Day)
}

function recalculate(rows, startDate) {
  let previous
  for (const row of rows) {
    const transit = previous ? distance(previous, row) : 0
    row.Start_Day = previous ? previous.End_Day + Math.ceil(transit / 50) + 1 : 0
    row.End_Day = row.Start_Day + row.Duration_Days + row.Mob_Demob_Days
    if (row.End_Day > 365) throw new Error('This order exceeds the 365-day planning horizon. Try another position.')
    row.Start_Date = new Date(Date.parse(startDate) + row.Start_Day * day).toISOString().slice(0, 10)
    row.End_Date = new Date(Date.parse(startDate) + row.End_Day * day).toISOString().slice(0, 10)
    row.Transit_Dist_km = Math.round(transit * 10) / 10
    previous = row
  }
}

export function restoreOrder(schedule, order, startDate) {
  if (order.length !== schedule.length || new Set(order).size !== order.length || order.some(id => !schedule.some(r => r.Well_ID === id))) throw new Error('The saved draft does not match this schedule.')
  const rows = schedule.map(row => ({ ...row })).sort((a, b) => a.Platform_Assigned.localeCompare(b.Platform_Assigned) || order.indexOf(a.Well_ID) - order.indexOf(b.Well_ID))
  for (const name of new Set(rows.map(r => r.Platform_Assigned))) recalculate(rows.filter(r => r.Platform_Assigned === name), startDate)
  return rows
}
