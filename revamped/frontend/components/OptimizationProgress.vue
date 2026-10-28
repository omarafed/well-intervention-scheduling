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
  </section>
</template>
