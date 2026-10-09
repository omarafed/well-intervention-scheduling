import { defineStore } from 'pinia'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({ tab: 'Overview', wells: [], platforms: [], jobs: [] }),
})
