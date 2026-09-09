/** Which tab is active in the Builds page */
export type BuildTab = 'tasks' | 'derive'

/** Per-tab active item counts for the stats bar */
export interface TabActiveCounts {
  pending: number
  running: number
}

/** Combined stats for both tabs */
export interface BuildsStats {
  tasks: TabActiveCounts
  derive: TabActiveCounts
  loading: boolean
}
