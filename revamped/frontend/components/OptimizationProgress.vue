<script setup>
const props = defineProps({ progress: { type: Object, default: () => ({}) }, status: { type: String, required: true } })
const queued = computed(() => ['queued', 'retrying'].includes(props.status))
const completed = computed(() => props.status === 'completed')
const elapsed = computed(() => Number(props.progress.elapsed_seconds || 0))
const limit = computed(() => Number(props.progress.time_limit_seconds || 45))
const percent = computed(() => completed.value ? 100 : Math.min(100, Math.max(0, Number(props.progress.search_seconds || 0) / limit.value * 100)))
const title = computed(() => {
  if (queued.value) return props.status === 'retrying' ? 'Waiting to retry optimization' : 'Waiting for an available worker'
  if (props.status === 'failed') return 'Optimization stopped'
  if (completed.value) return 'Optimization complete'
  return { building: 'Preparing the scheduling model', searching: 'Searching for better schedules', finalizing: 'Calculating risk analysis' }[props.progress.phase] || 'Starting optimization'
})
const format = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
const history = computed(() => props.progress.history || [])
const convergence = computed(() => [
  { type: 'scatter', mode: 'lines+markers', name: 'Best schedule score', x: history.value.map(p => p.elapsed_seconds), y: history.value.map(p => p.objective), line: { color: '#0f766e', shape: 'hv' }, marker: { size: 5 } },
  { type: 'scatter', mode: 'lines', name: 'Solver upper bound', x: history.value.map(p => p.elapsed_seconds), y: history.value.map(p => p.best_bound), line: { color: '#d97706', dash: 'dash', shape: 'hv' } },
])
</script>

<template>
  <section class="card p-6 space-y-4" aria-label="Optimization progress">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div><p class="eyebrow">{{ completed ? 'Finished run' : 'Live optimization' }}</p><h3 class="font-semibold mt-1" role="status">{{ title }}</h3></div>
      <span class="text-sm text-slate-500">{{ queued ? 'Queued' : `${format(elapsed)}s elapsed` }}</span>
    </div>
    <div class="h-2.5 rounded-full bg-slate-100 overflow-hidden" role="progressbar" aria-label="Optimization search time budget" :aria-valuenow="queued ? undefined : Math.round(percent)" aria-valuemin="0" aria-valuemax="100" :aria-valuetext="queued ? 'Waiting for a worker' : completed ? 'Completed' : `${Math.round(percent)} percent of search time budget used`">
      <div class="h-full rounded-full bg-teal-600 transition-all duration-700" :class="queued ? 'w-1/5 animate-pulse' : ''" :style="queued ? {} : {width: percent + '%'}" />
    </div>
    <p class="text-xs text-slate-500">{{ completed ? 'Final schedule and risk results are ready.' : queued ? 'Your search starts when a worker is available.' : `Updates every 5 seconds · Search budget: ${limit}s. This bar measures time used; the solver may finish early.` }}</p>
    <div v-if="!queued && progress.solutions" class="grid sm:grid-cols-3 gap-4">
      <div><p class="text-xs text-slate-500">Improving solutions found</p><p class="font-semibold mt-1">{{ progress.solutions }}</p></div>
      <div><p class="text-xs text-slate-500">Best schedule score ↑</p><p class="font-semibold mt-1">{{ format(progress.objective) }}</p></div>
      <div><p class="text-xs text-slate-500">Gap to solver upper bound</p><p class="font-semibold mt-1">{{ progress.gap_percent == null ? '—' : format(progress.gap_percent) + '%' }}</p></div>
    </div>
    <p v-if="!queued && !progress.solutions && !completed" class="text-sm text-slate-500">No feasible schedule found yet. The timeline and routes will appear when the solver finds its first solution.</p>
    <template v-if="history.length">
      <p class="text-xs text-slate-500">A higher schedule score means a better balance of earlier production and shorter transit. The gap narrows as the solver improves the schedule or its upper bound.</p>
      <ClientOnly><Chart :data="convergence" :layout="{height:250, margin:{t:15,r:20,b:60,l:90}, xaxis:{title:{text:'Elapsed time (seconds)'}}, yaxis:{title:{text:'Search score'}}, legend:{orientation:'h',y:-0.3}}" /></ClientOnly>
    </template>
  </section>
</template>
