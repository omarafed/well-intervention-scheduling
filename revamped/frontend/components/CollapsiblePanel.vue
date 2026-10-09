<script setup>
const props = defineProps({ title: { type: String, required: true }, defaultOpen: { type: Boolean, default: false } })
const expanded = ref(props.defaultOpen)
</script>

<template>
  <details class="card collapsible-panel" :open="defaultOpen" @toggle="expanded = $event.target.open">
    <summary class="flex items-center justify-between gap-3 p-5 cursor-pointer font-semibold text-sm">
      <span>{{ title }}</span><span class="collapse-chevron text-slate-400" aria-hidden="true">⌄</span>
    </summary>
    <div v-if="expanded" class="px-5 pb-5 min-w-0"><slot /></div>
  </details>
</template>
