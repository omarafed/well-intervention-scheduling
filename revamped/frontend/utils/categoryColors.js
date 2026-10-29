const categoryColors = {
  'Downhole Logging, Survey & Test': '#6366f1',
  'Wellhead Maintenance': '#0f766e',
  'Slickline Services': '#d97706',
  'CTU Services': '#db2777',
  'Sand Control & Monitoring': '#0284c7',
  Perforation: '#9333ea',
  'Well Repair & Maintenance': '#4d7c0f',
  'Well Stimulation': '#c2410c',
  'Artificial Lift Enhancement': '#475569',
}

// Derive custom category colors from the name, independent of row order.
export function categoryColor(category) {
  const name = String(category || '').trim()
  if (Object.hasOwn(categoryColors, name)) return categoryColors[name]
  let hash = 0
  for (const character of name) hash = (Math.imul(hash, 31) + character.codePointAt(0)) >>> 0
  return `hsl(${hash % 360}, 65%, 35%)`
}
