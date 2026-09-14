import type { Analysis, Player, PlayerPoolEntry } from './types'

export function teamPalette(teamId: number): [string, string] {
  const palettes: Array<[string, string]> = [
    ['#cf1538', '#f5f2e8'], ['#6b1439', '#9ed3eb'], ['#b41028', '#171b34'],
    ['#d51b38', '#f6f2e8'], ['#2457a6', '#f5f2e8'], ['#1744a0', '#f5f2e8'],
    ['#79bde8', '#6c1739'], ['#17365f', '#f3c857'], ['#17365f', '#f5f2e8'],
    ['#111827', '#f5f2e8'], ['#ef6a31', '#111827'], ['#17365f', '#f5f2e8'],
    ['#f3c93b', '#174e8d'], ['#cf1734', '#f5f2e8'], ['#89c9ee', '#f5f2e8'],
    ['#d91e36', '#f5f2e8'], ['#111827', '#f5f2e8'], ['#d91e36', '#f5f2e8'],
    ['#f5f2e8', '#17365f'], ['#efc727', '#111827'],
  ]
  return palettes[(teamId - 1) % palettes.length]
}

export function poolPlayer(player: PlayerPoolEntry): Player {
  return {
    ...player,
    minutesBands: null,
    warnings: [
      ...(player.news ? [player.news] : []),
      ...(player.status !== 'a' ? ['Availability is flagged'] : []),
    ],
    components: {},
    setPieceDutyChanges: [],
  }
}

export function findPlayer(analysis: Analysis, id: number): Player | undefined {
  return analysis.players[String(id)] ?? (() => {
    const player = analysis.playerPool.find((row) => row.id === id)
    return player ? poolPlayer(player) : undefined
  })()
}

export function findPlayerForWeek(analysis: Analysis, id: number, gw: number): Player | undefined {
  const base = findPlayer(analysis, id)
  const pool = analysis.playerPool.find((row) => row.id === id)
  const week = pool?.gameweeks.find((row) => row.gw === gw)
  return base && week ? {
    ...base,
    gameweekXP: week.xP,
    opponent: week.opponent,
    home: week.home,
  } : base
}
