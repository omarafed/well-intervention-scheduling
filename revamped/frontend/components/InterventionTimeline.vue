<script setup>
import { categoryColor } from '../utils/categoryColors.js'
const props = defineProps({ rows: { type: Array, required: true }, startDate: { type: String, required: true }, editable: Boolean })
const emit = defineEmits(['move'])
const dragging = ref(null)
const tooltip = ref(null)
function showDetails(event, row) {
  const rect = event.currentTarget.getBoundingClientRect()
  tooltip.value = { row, left: Math.max(8, Math.min(rect.left, window.innerWidth - 280)), top: Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 205)) }
}
const groups = computed(() => [...new Set(props.rows.map(r => r.Platform_Assigned))].map(name => ({ name, rows: props.rows.filter(r => r.Platform_Assigned === name).sort((a, b) => a.Start_Day - b.Start_Day) })))
const categories = computed(() => [...new Set(props.rows.map(r => r['Job Category']))].sort())
const endDay = date => (Date.parse(date) - Date.parse(props.startDate)) / 86400000
const horizon = computed(() => Math.max(30, ...props.rows.map(r => r.End_Day + 5), ...props.rows.map(r => Number.isFinite(endDay(r.Contract_End_Date)) ? endDay(r.Contract_End_Date) + 10 : 0)))
const position = value => Math.max(0, value / horizon.value * 100) + '%'
const dateAt = value => new Date(Date.parse(props.startDate) + value * 86400000).toISOString().slice(0, 10)
function drop(event, target) {
  if (!dragging.value || !props.editable) return
  const rect = event.currentTarget.getBoundingClientRect()
  emit('move', dragging.value, target, event.clientX > rect.left + rect.width / 2)
  dragging.value = null
}
</script>

<template>
  <div class="overflow-x-auto pb-4">
    <p v-if="editable" class="text-xs text-slate-500 mb-4">Drag a well onto the left or right half of another well to place it before or after that well on the same rig. Focus a well and use ← / → to reorder with the keyboard. Locked wells keep their rig and start date.</p>
    <div class="min-w-[720px] pr-5">
      <div class="ml-36 relative h-8 text-xs text-slate-500"><span v-for="tick in [0,1,2,3,4]" :key="tick" class="absolute whitespace-nowrap" :style="{left:position(tick * horizon / 4),transform:tick === 4 ? 'translateX(-100%)' : ''}">{{ dateAt(tick * horizon / 4) }}</span></div>
      <div v-for="group in groups" :key="group.name" class="flex items-center border-t border-slate-100">
        <span class="w-36 shrink-0 text-xs font-semibold pr-3">{{ group.name }}</span>
        <div class="relative flex-1 h-36 bg-slate-50">
          <div v-if="Number.isFinite(endDay(group.rows[0].Contract_End_Date))" class="absolute top-1 bottom-1 border-l-2 border-dashed border-red-500 pointer-events-none" :style="{left:position(endDay(group.rows[0].Contract_End_Date))}"><span class="absolute top-0 right-1 whitespace-nowrap text-[10px] text-red-700 bg-white/90 px-1">Contract end {{ group.rows[0].Contract_End_Date }}</span></div>
          <button v-for="(row, index) in group.rows" :key="row.Well_ID" type="button" class="timeline-well absolute top-9 h-24 rounded text-white text-xs text-left px-1 overflow-visible min-w-[8px]" :class="editable && !row.Locked ? 'cursor-grab active:cursor-grabbing' : 'cursor-default'" :style="{left:position(row.Start_Day),width:position(Math.max(row.End_Day-row.Start_Day, .5)),background:categoryColor(row['Job Category'])}" :draggable="editable && !row.Locked" @mouseenter="showDetails($event, row)" @mouseleave="tooltip = null" @focus="showDetails($event, row)" @blur="tooltip = null" @keydown.esc="tooltip = null" :aria-label="`${row.Well_ID}, ${row['Job Category']}, ${row.Start_Date} to ${row.End_Date}, ${row.BOPD} BOPD, cost ${row.Cost_kUSD} kUSD, contract end ${row.Contract_End_Date || 'not specified'}`" @dragstart="tooltip = null; dragging = row.Well_ID; $event.dataTransfer.setData('text/plain', row.Well_ID); $event.dataTransfer.effectAllowed = 'move'" @dragend="dragging = null" @dragover.prevent @drop.prevent="drop($event, row.Well_ID)" @keydown.left.prevent="editable && index > 0 && emit('move', row.Well_ID, group.rows[index-1].Well_ID, false)" @keydown.right.prevent="editable && index < group.rows.length-1 && emit('move', row.Well_ID, group.rows[index+1].Well_ID, true)">
            <span class="timeline-bar-label">{{ row.Locked ? '🔒 ' : '' }}{{ row.Well_ID }}<br>{{ row.BOPD }} BOPD</span>

          </button>
        </div>
      </div>
    </div>
    <div class="flex flex-wrap gap-x-4 gap-y-2 mt-4 text-xs"><span v-for="category in categories" :key="category"><i class="inline-block w-2.5 h-2.5 rounded-sm mr-1" :style="{background:categoryColor(category)}" />{{ category }}</span></div>
  </div>
  <Teleport to="body">
    <div v-if="tooltip" role="tooltip" class="fixed z-50 w-64 p-3 rounded-lg bg-slate-800 text-white text-xs shadow-xl pointer-events-none" :style="{left:tooltip.left+'px', top:tooltip.top+'px'}"><b>{{ tooltip.row.Well_ID }}</b><br>Category: {{ tooltip.row['Job Category'] }}<br>Locked: {{ tooltip.row.Locked ? 'Yes' : 'No' }}<br>Start: {{ tooltip.row.Start_Date }}<br>End: {{ tooltip.row.End_Date }}<br>Gain: {{ tooltip.row.BOPD }} BOPD<br>Cost: ${{ tooltip.row.Cost_kUSD.toLocaleString() }}k<br>Contract ends: {{ tooltip.row.Contract_End_Date || 'Not specified' }}</div>
  </Teleport>
</template>

<style scoped>
.timeline-bar-label { writing-mode: vertical-rl; max-height: 100%; overflow: hidden; white-space: nowrap; font-size: 10px; font-weight: 700; }
.timeline-well:hover, .timeline-well:focus-visible { z-index: 10; }
</style>
