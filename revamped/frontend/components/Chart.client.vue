<script setup>
const props = defineProps({ data: { type: Array, default: () => [] }, layout: { type: Object, default: () => ({}) } })
const el = ref(null)
let plotly
let disposed = false
async function draw() {
  if (disposed || !plotly || !el.value) return
  await plotly.react(el.value, props.data, {
    autosize: true, height: 380, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: { family: 'system-ui', color: '#475569' }, margin: { t: 25, r: 25, b: 55, l: 100 }, ...props.layout,
  }, { responsive: true, displaylogo: false })
}
function resize() { if (plotly && el.value) plotly.Plots.resize(el.value) }
onMounted(async () => {
  const module = await import('plotly.js-dist-min')
  plotly = module.default || module
  if (disposed) return
  await draw()
  window.addEventListener('resize', resize)
})
watch(() => [props.data, props.layout], draw, { deep: true })
onBeforeUnmount(() => { disposed = true; window.removeEventListener('resize', resize); if (plotly && el.value) plotly.purge(el.value) })
</script>
<template><div ref="el" class="w-full min-h-80" /></template>
