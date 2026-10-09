import { defineStore } from 'pinia'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({ wells: [], platforms: [], jobs: [] }),
})
