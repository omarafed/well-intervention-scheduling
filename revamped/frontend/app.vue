<script setup>
const workspace = useWorkspaceStore()
const { tab, wells, platforms, jobs } = storeToRefs(workspace)
const config = useRuntimeConfig()
const tabs = ['Overview', 'Wells', 'Platforms', 'Scenarios']
const error = ref('')
const notice = ref('')
const busy = ref(false)
const selected = ref(null)
const scenario = reactive({ name: 'Intervention plan', start_date: new Date().toLocaleDateString('en-CA'), dropped_wells: [] })
const well = reactive({ name: '', category: 'Wellhead Maintenance', duration_days: 7, gain_bopd: 500, lat: 4.1, lon: 112.2 })
const platform = reactive({ name: '', type: 'Intervention', categories: [], mob_demob_days: 2, daily_cost_kusd: 12, contract_end_date: '' })
const editingWell = ref(null), editingPlatform = ref(null)
const customCategories = ref('')
const categories = ['Downhole Logging, Survey & Test', 'Wellhead Maintenance', 'Slickline Services', 'CTU Services', 'Sand Control & Monitoring', 'Perforation', 'Well Repair & Maintenance', 'Well Stimulation', 'Artificial Lift Enhancement']
const colors = ['#0f766e', '#6366f1', '#d97706', '#e11d48', '#0284c7', '#7c3aed']
let timer
let refreshing = false
let refreshingJob = false
let selectionVersion = 0
const result = computed(() => selected.value?.result)
const schedule = computed(() => result.value?.schedule || [])
const activeJobs = computed(() => jobs.value.filter(j => ['queued', 'running', 'retrying'].includes(j.status)))
const isOptimizing = computed(() => selected.value?.job.kind === 'optimization' && ['queued', 'running', 'retrying'].includes(selected.value.job.status))
const previewCaption = computed(() => {
  const progress = selected.value?.progress
  if (progress?.elapsed_seconds == null) return 'Waiting for the worker · Refreshes every 5 seconds'
  return `Snapshot at ${num(progress.elapsed_seconds, 1)}s · ${num(progress.solutions)} solutions found · Refreshes every 5 seconds`
})
async function api(path, options = {}) {
  try {
    return await $fetch(config.public.apiBase + path, options)
  } catch (e) {
    throw new Error(e.data?.message || e.message || 'Request failed')
  }
}
async function action(fn) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function load() {
  if (refreshing) return
  refreshing = true
  try {
    const [w, p, j] = await Promise.all([api('/wells'), api('/platforms'), api('/jobs')])
    wells.value = w; platforms.value = p; jobs.value = j
  } finally { refreshing = false }
}
async function selectJob(id) {
  const version = ++selectionVersion
  const data = await api('/jobs/' + id)
  if (version === selectionVersion) selected.value = data
}
async function refreshActiveJob() {
  if (refreshingJob || !selected.value || !['queued', 'running', 'retrying'].includes(selected.value.job.status)) return
  const id = selected.value.job.id
  const version = selectionVersion
  refreshingJob = true
  try {
    const data = await api('/jobs/' + id)
    if (version === selectionVersion && selected.value?.job.id === id) selected.value = data
  } finally { refreshingJob = false }
}
async function saveWell() {
  await action(async () => {
    await api('/wells' + (editingWell.value ? '/' + editingWell.value : ''), { method: editingWell.value ? 'PUT' : 'POST', body: well })
    editingWell.value = null; well.name = ''; notice.value = 'Well saved.'; await load()
  })
}
async function savePlatform() {
  await action(async () => {
    const extra = customCategories.value.split(';').map(x => x.trim()).filter(Boolean)
    await api('/platforms' + (editingPlatform.value ? '/' + editingPlatform.value : ''), { method: editingPlatform.value ? 'PUT' : 'POST', body: { ...platform, categories: [...new Set([...platform.categories, ...extra])] } })
    editingPlatform.value = null; platform.name = ''; customCategories.value = ''; notice.value = 'Platform saved.'; await load()
  })
}
function editWell(row) { Object.assign(well, row); editingWell.value = row.id }
function editPlatform(row) { Object.assign(platform, row, { categories: [...row.categories] }); editingPlatform.value = row.id; customCategories.value = '' }
async function remove(kind, row) {
  if (!confirm(`Delete ${row.name}? Saved scenario results will remain available.`)) return
  await action(async () => { await api(`/${kind}/${row.id}`, { method: 'DELETE' }); await load() })
}
async function importFile(kind, event) {
  const file = event.target.files?.[0]; if (!file) return
  await action(async () => {
    const body = new FormData(); body.append('file', file)
    const job = await api('/imports/' + kind, { method: 'POST', body })
    notice.value = 'Import queued. Check its status in Scenarios.'
    await load(); await selectJob(job.id); tab.value = 'Scenarios'
  })
  event.target.value = ''
}
async function optimize() {
  await action(async () => {
    const job = await api('/optimizations', { method: 'POST', body: scenario })
    await load(); await selectJob(job.id); tab.value = 'Scenarios'
  })
}
async function demo() { await action(async () => { await api('/demo', { method: 'POST' }); await load(); notice.value = 'Demo data loaded. You can now run your first scenario.' }) }
function csvDownload(filename, rows) {
  if (!rows.length) return
  const keys = Object.keys(rows[0])
  const quote = value => '"' + String(value ?? '').replace(/"/g, '""') + '"'
  const csv = [keys.map(quote).join(','), ...rows.map(row => keys.map(key => quote(row[key])).join(','))].join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url)
}
function exportMC() {
  const mc = result.value?.monte_carlo
  if (mc) csvDownload('monte-carlo.csv', mc.gain_bopd.map((gain, i) => ({ iteration: i + 1, gain_bopd: gain, cost_kusd: mc.cost_kusd[i] })))
}
function template(kind) {
  const rows = kind === 'wells' ? [{ Well_ID: 'WELL-01', 'Job Category': 'Wellhead Maintenance', Duration_Days: 7, Gain_BOPD: 500, Lat: 4.1, Lon: 112.2 }] : [{ Platform_Name: 'Platform-1', Type: 'Intervention', Supported_Job_Categories: 'Wellhead Maintenance;Slickline Services', Mob_Demob_Days: 2, Daily_Cost_kUSD: 12, Contract_End_Date: '' }]
  csvDownload(kind + '-template.csv', rows)
}
const gantt = computed(() => [...new Set(schedule.value.map(r => r.Platform_Assigned))].map((name, i) => {
  const rows = schedule.value.filter(r => r.Platform_Assigned === name)
  return { type: 'bar', orientation: 'h', name, y: rows.map(() => name), x: rows.map(r => (r.End_Day - r.Start_Day) * 86400000), base: rows.map(r => r.Start_Date), text: rows.map(r => r.Well_ID), marker: { color: colors[i % colors.length] }, hovertext: rows.map(r => `${r.Well_ID} · ${r['Job Category']}<br>${r.Start_Date} → ${r.End_Date}<br>${r.BOPD} BOPD`), hoverinfo: 'text' }
}))
const routes = computed(() => [...new Set(schedule.value.map(r => r.Platform_Assigned))].map((name, i) => {
  const rows = schedule.value.filter(r => r.Platform_Assigned === name)
  return { type: 'scattergeo', mode: 'lines+markers+text', name, lat: rows.map(r => r.Lat), lon: rows.map(r => r.Lon), text: rows.map((r, j) => `${j + 1}. ${r.Well_ID}`), textposition: 'top center', line: { color: colors[i % colors.length] }, marker: { size: 9 } }
}))
const num = (value, digits = 0) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits })
onMounted(async () => {
  await action(load)
  timer = setInterval(async () => {
    // Active previews refresh independently of slower dataset requests and form actions.
    const tasks = [refreshActiveJob()]
    if (!busy.value) tasks.push(load())
    const outcomes = await Promise.allSettled(tasks)
    for (const outcome of outcomes) if (outcome.status === 'rejected') error.value = outcome.reason.message
  }, 5000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="min-h-screen">
    <header class="bg-teal-950 text-white"><div class="max-w-7xl mx-auto px-6 py-5 flex flex-wrap gap-4 items-center justify-between"><div class="font-semibold tracking-widest text-sm">BAYU <span class="text-teal-400">/</span> <span class="text-teal-100/70 font-normal">PLATFORM SCHEDULING</span></div></div></header>
    <nav class="border-b border-slate-200 bg-white"><div class="max-w-7xl mx-auto px-6 flex gap-7"><button v-for="item in tabs" :key="item" class="py-4 text-sm border-b-2" :class="tab === item ? 'border-teal-600 text-teal-700 font-semibold' : 'border-transparent text-slate-500'" @click="tab = item">{{ item }}</button></div></nav>
    <main class="max-w-7xl mx-auto p-6 lg:py-10 space-y-6">
      <div v-if="error" role="alert" class="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-800">{{ error }}</div>
      <div v-if="notice" role="status" class="rounded-lg bg-teal-50 border border-teal-200 p-4 text-sm text-teal-800">{{ notice }}</div>

      <template v-if="tab === 'Overview'">
        <div class="flex flex-wrap justify-between gap-4"><div><p class="eyebrow">Operations workspace</p><h1 class="text-3xl font-semibold mt-2">Plan the next intervention.</h1><p class="text-slate-500 mt-2">Build a platform fleet, prepare wells, and compare saved scenarios.</p></div><button v-if="!wells.length && !platforms.length" class="secondary self-start" :disabled="busy" @click="demo">Load demo data</button></div>
        <div class="grid sm:grid-cols-3 gap-5"><div v-for="metric in [{ label: 'Candidate wells', value: wells.length }, { label: 'Available platforms', value: platforms.length }, { label: 'Active jobs', value: activeJobs.length }]" :key="metric.label" class="card p-6"><p class="text-sm text-slate-500">{{ metric.label }}</p><p class="text-4xl mt-3 font-semibold">{{ metric.value }}</p></div></div>
        <form class="card p-6 space-y-5" @submit.prevent="optimize"><div><h2 class="text-lg font-semibold">Create a scenario</h2><p class="text-sm text-slate-500 mt-1">Optimize a 365-day horizon for earlier production and shorter transit. Each run saves a snapshot of your inputs.</p></div><div class="field-grid"><label>Scenario name<input v-model="scenario.name" required maxlength="100"></label><label>Planning start<input v-model="scenario.start_date" type="date" required></label><div class="flex items-end"><button class="btn w-full" :disabled="busy || !wells.length || !platforms.length">Run optimization →</button></div></div><details v-if="wells.length"><summary class="text-sm cursor-pointer text-slate-500">Exclude wells from this scenario ({{ scenario.dropped_wells.length }})</summary><div class="grid sm:grid-cols-4 gap-3 mt-4"><label v-for="w in wells" :key="w.id" class="flex gap-2 items-center"><input v-model="scenario.dropped_wells" type="checkbox" :value="w.name">{{ w.name }}</label></div></details></form>
        <div class="card p-6"><h2 class="text-lg font-semibold">Start with your data</h2><div class="grid md:grid-cols-3 gap-8 mt-5"><div><span class="eyebrow">01 / Prepare</span><h3 class="font-medium mt-2">Add wells and platforms</h3><p class="text-sm text-slate-500 mt-2">Enter records manually or import CSV and Excel datasets.</p></div><div><span class="eyebrow">02 / Optimize</span><h3 class="font-medium mt-2">Run a saved scenario</h3><p class="text-sm text-slate-500 mt-2">Allocate compatible platforms and sequence interventions.</p></div><div><span class="eyebrow">03 / Evaluate</span><h3 class="font-medium mt-2">Explore outcomes</h3><p class="text-sm text-slate-500 mt-2">Review timelines, routes, costs, and 10,000 risk simulations.</p></div></div></div>
      </template>

      <template v-if="tab === 'Wells'">
        <div class="flex flex-wrap justify-between items-center gap-3"><div><p class="eyebrow">Input dataset</p><h1 class="text-3xl font-semibold mt-2">Candidate wells</h1></div><div class="flex gap-3"><button class="secondary" @click="template('wells')">CSV template</button><label class="secondary cursor-pointer">Import CSV / XLSX<input class="hidden" type="file" accept=".csv,.xlsx" :disabled="busy" @change="importFile('wells', $event)"></label></div></div>
        <form class="card p-6 space-y-4" @submit.prevent="saveWell"><h2 class="font-semibold">{{ editingWell ? 'Edit well' : 'Add a well' }}</h2><div class="field-grid"><label>Well name<input v-model="well.name" required maxlength="100"></label><label>Job category<input v-model="well.category" list="categories" required></label><label>Duration (days)<input v-model.number="well.duration_days" type="number" min="0" max="365" required></label><label>Production gain (BOPD)<input v-model.number="well.gain_bopd" type="number" min="0" max="10000000" required></label><label>Latitude<input v-model.number="well.lat" type="number" step="any" min="-90" max="90" required></label><label>Longitude<input v-model.number="well.lon" type="number" step="any" min="-180" max="180" required></label></div><div class="flex gap-3"><button class="btn" :disabled="busy">Save well</button><button v-if="editingWell" type="button" class="secondary" @click="editingWell = null; well.name = ''">Cancel edit</button></div></form>
        <div class="card overflow-x-auto"><table class="w-full"><thead><tr><th>Well</th><th>Category</th><th>Days</th><th>Gain / BOPD</th><th>Coordinates</th><th>Actions</th></tr></thead><tbody><tr v-for="row in wells" :key="row.id"><td class="font-semibold">{{ row.name }}</td><td>{{ row.category }}</td><td>{{ row.duration_days }}</td><td>{{ num(row.gain_bopd) }}</td><td>{{ row.lat }}, {{ row.lon }}</td><td class="whitespace-nowrap"><button class="text-teal-700 mr-3" @click="editWell(row)">Edit</button><button class="text-red-600" :disabled="busy" @click="remove('wells', row)">Delete</button></td></tr><tr v-if="!wells.length"><td colspan="6" class="!py-10 text-center text-slate-500">No wells yet. Add a well or import your dataset.</td></tr></tbody></table></div>
      </template>

      <template v-if="tab === 'Platforms'">
        <div class="flex flex-wrap justify-between items-center gap-3"><div><p class="eyebrow">Fleet configuration</p><h1 class="text-3xl font-semibold mt-2">Platforms</h1></div><div class="flex gap-3"><button class="secondary" @click="template('platforms')">CSV template</button><label class="secondary cursor-pointer">Import CSV / XLSX<input class="hidden" type="file" accept=".csv,.xlsx" :disabled="busy" @change="importFile('platforms', $event)"></label></div></div>
        <form class="card p-6 space-y-4" @submit.prevent="savePlatform"><h2 class="font-semibold">{{ editingPlatform ? 'Edit platform' : 'Add a platform' }}</h2><div class="field-grid"><label>Platform name<input v-model="platform.name" required maxlength="100"></label><label>Type<input v-model="platform.type"></label><label>Mobilization / demobilization (days)<input v-model.number="platform.mob_demob_days" type="number" min="0" max="365" required></label><label>Daily cost (kUSD)<input v-model.number="platform.daily_cost_kusd" type="number" min="0.001" max="1000000" step="0.001" required></label><label>Contract end (advisory)<input v-model="platform.contract_end_date" type="date"></label><label>Additional categories (semicolon separated)<input v-model="customCategories"></label></div><fieldset><legend class="text-xs font-semibold text-slate-500 mb-3">Supported job categories</legend><div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3"><label v-for="category in [...new Set([...categories, ...platform.categories])]" :key="category" class="flex items-center gap-2 font-normal"><input v-model="platform.categories" type="checkbox" :value="category">{{ category }}</label></div></fieldset><div class="flex gap-3"><button class="btn" :disabled="busy">Save platform</button><button v-if="editingPlatform" type="button" class="secondary" @click="editingPlatform = null; platform.name = ''; platform.categories = []">Cancel edit</button></div></form>
        <div class="grid md:grid-cols-2 gap-5"><article v-for="row in platforms" :key="row.id" class="card p-6"><div class="flex justify-between"><h2 class="text-lg font-semibold">{{ row.name }}</h2><span class="text-sm text-slate-500">{{ row.type }}</span></div><p class="mt-4 text-sm">${{ num(row.daily_cost_kusd, 3) }}k / day · {{ row.mob_demob_days }} mobilization days</p><p class="text-xs text-slate-500 mt-2">Contract end: {{ row.contract_end_date || 'Not specified' }}</p><div class="flex flex-wrap gap-2 mt-4"><span v-for="cat in row.categories" :key="cat" class="text-xs px-2 py-1 bg-teal-50 text-teal-800 rounded-md">{{ cat }}</span></div><div class="mt-5 flex gap-4 text-sm"><button class="text-teal-700" @click="editPlatform(row)">Edit platform</button><button class="text-red-600" :disabled="busy" @click="remove('platforms', row)">Delete</button></div></article><div v-if="!platforms.length" class="card p-10 text-slate-500 md:col-span-2 text-center">No platforms yet. Add one with supported job categories to begin.</div></div>
      </template>

      <template v-if="tab === 'Scenarios'">
        <div><p class="eyebrow">Saved runs & imports</p><h1 class="text-3xl font-semibold mt-2">Scenario history</h1><p class="text-sm text-slate-500 mt-2">Progress updates every 5 seconds. Watch the best schedule improve during the search.</p></div>
        <div class="card overflow-x-auto"><table class="w-full"><thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody><tr v-for="job in jobs" :key="job.id" :class="selected?.job.id === job.id ? 'bg-teal-50/50' : ''"><td class="font-semibold">{{ job.name }}</td><td>{{ job.kind }}</td><td><span class="rounded-full px-2 py-1 text-xs" :class="job.status === 'completed' ? 'bg-teal-100 text-teal-800' : job.status === 'failed' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'">{{ job.status }}</span></td><td>{{ new Date(job.created_at).toLocaleString() }}</td><td><button class="text-teal-700" @click="action(() => selectJob(job.id))">View</button></td></tr><tr v-if="!jobs.length"><td colspan="5" class="text-center !py-10 text-slate-500">No runs yet. Create your first scenario from Overview.</td></tr></tbody></table></div>
        <section v-if="selected" class="space-y-5"><div class="flex flex-wrap gap-3 items-center justify-between"><h2 class="text-xl font-semibold">{{ selected.job.name }}</h2><div v-if="schedule.length" class="flex gap-3"><button class="secondary" @click="csvDownload('platform-schedule.csv', schedule)">Export schedule</button><button v-if="result?.monte_carlo" class="secondary" @click="exportMC">Export Monte Carlo</button></div></div><p v-if="selected.job.error" role="alert" class="text-red-700 text-sm">{{ selected.job.error }}</p><OptimizationProgress v-if="selected.job.kind === 'optimization' && (selected.progress?.phase || ['running', 'queued', 'retrying'].includes(selected.job.status))" :progress="selected.progress || {}" :status="selected.job.status" /><p v-if="selected.job.kind !== 'optimization' && ['running', 'queued', 'retrying'].includes(selected.job.status)" role="status" class="card p-8 text-slate-500">{{ selected.job.status === 'running' ? 'Processing your dataset. Results will appear here.' : 'Waiting for a worker. This page refreshes automatically.' }}</p><p v-if="result?.imported" class="card p-6">Imported {{ result.imported }} {{ result.kind }}. Matching names have been updated.</p>
          <template v-if="schedule.length"><p v-if="selected.job.status !== 'completed'" role="status" class="rounded-lg bg-teal-50 text-teal-800 p-4 text-sm">Best schedule so far — provisional. The timeline, routes, and totals update when a better solution is found. Risk analysis is calculated after the search finishes.</p><div class="grid sm:grid-cols-4 gap-4"><div v-for="metric in [{label:'Solver',value:result.status},{label:'Production gain',value:num(result.summary.gain_bopd)+' BOPD'},{label:'Intervention cost',value:'$'+num(result.summary.cost_kusd,3)+'k'},{label:'Fleet transit',value:num(result.summary.transit_km,1)+' km'}]" :key="metric.label" class="card p-5"><p class="text-xs text-slate-500">{{ metric.label }}</p><p class="text-xl font-semibold mt-2">{{ metric.value }}</p></div></div><p v-for="warning in result.warnings" :key="warning" class="text-amber-800 bg-amber-50 rounded-lg p-4 text-sm">{{ warning }}</p>
          </template>
          <div v-if="schedule.length || isOptimizing" class="space-y-5">
            <div class="card p-5"><div class="flex flex-wrap items-center justify-between gap-2"><h3 class="font-semibold">Intervention timeline</h3><span v-if="isOptimizing" class="text-xs font-medium text-teal-700">Live · Every 5 seconds</span></div><p v-if="isOptimizing" data-testid="timeline-snapshot" class="text-xs text-slate-500 mt-2">{{ previewCaption }}</p><ClientOnly v-if="schedule.length"><Chart :data="gantt" :layout="{ barmode: 'overlay', xaxis: { type: 'date' }, yaxis: { autorange: 'reversed' }, showlegend: false }" /></ClientOnly><p v-else class="py-16 text-center text-sm text-slate-500">Waiting for the first feasible schedule. The latest preview will appear here automatically.</p></div>
            <div class="card p-5"><div class="flex flex-wrap items-center justify-between gap-2"><h3 class="font-semibold">Platform routes</h3><span v-if="isOptimizing" class="text-xs font-medium text-teal-700">Live · Every 5 seconds</span></div><p v-if="isOptimizing" data-testid="routes-snapshot" class="text-xs text-slate-500 mt-2">{{ previewCaption }}</p><ClientOnly v-if="schedule.length"><Chart :data="routes" :layout="{ geo: { fitbounds: 'locations', showland: true, landcolor: '#f1f5f9', showocean: true, oceancolor: '#e0f2fe', showcountries: true }, margin: {t: 25, b: 25, l: 25, r: 25} }" /></ClientOnly><p v-else class="py-16 text-center text-sm text-slate-500">Waiting for the first feasible schedule. The latest preview will appear here automatically.</p></div>
          </div>
          <template v-if="schedule.length">
            <div v-if="result?.risk" class="grid lg:grid-cols-2 gap-5"><div v-for="kind in ['gain','cost']" :key="kind" class="card p-5"><h3 class="font-semibold">{{ kind === 'gain' ? 'Production gain uncertainty' : 'Cost uncertainty' }}</h3><p class="text-xs text-slate-500 mt-2">10,000 triangular simulations · {{ kind === 'gain' ? 'BOPD' : 'kUSD' }}</p><div class="flex gap-5 text-sm mt-3"><span v-for="percentile in ['p10','p50','p90']" :key="percentile">{{ percentile.toUpperCase() }}: <b>{{ num(result.risk[kind][percentile], 1) }}</b></span></div><ClientOnly><Chart :data="[{type:'bar',x:result.risk[kind+'_histogram'].x,y:result.risk[kind+'_histogram'].y,marker:{color:kind==='gain'?'#0f766e':'#d97706'}}]" :layout="{height:280,margin:{t:20,r:20,b:50,l:55},xaxis:{title:{text:kind==='gain'?'Gain (BOPD)':'Cost (kUSD)'}},yaxis:{title:{text:'Iterations'}}}" /></ClientOnly></div></div>
            <div class="card overflow-x-auto"><table class="w-full"><thead><tr><th>Well</th><th>Platform</th><th>Start</th><th>End</th><th>Gain / BOPD</th><th>Cost / kUSD</th></tr></thead><tbody><tr v-for="row in schedule" :key="row.Well_ID"><td class="font-semibold">{{ row.Well_ID }}</td><td>{{ row.Platform_Assigned }}</td><td>{{ row.Start_Date }}</td><td>{{ row.End_Date }}</td><td>{{ num(row.BOPD) }}</td><td>{{ num(row.Cost_kUSD,3) }}</td></tr></tbody></table></div>
          </template>
          <details v-if="selected.job.kind === 'optimization'" class="card p-5"><summary class="text-sm cursor-pointer font-medium">Saved scenario inputs</summary><pre class="text-xs mt-4 overflow-auto max-h-96">{{ JSON.stringify(selected.input, null, 2) }}</pre></details>
        </section>
      </template>
      <datalist id="categories"><option v-for="cat in categories" :key="cat" :value="cat" /></datalist>
    </main>
  </div>
</template>
