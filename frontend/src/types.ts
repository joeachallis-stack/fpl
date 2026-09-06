export type Room = 'gameweek' | 'experts' | 'fixtures' | 'model'

export type Player = {
  id: number
  name: string
  fullName: string
  teamId: number
  team: string
  teamShort: string
  position: 'GKP' | 'DEF' | 'MID' | 'FWD'
  opponent: string
  home: boolean
  expectedMinutes: number | null
  minutesBands: { p_zero: number; p_1_59: number; p_60_plus: number } | null
  gameweekXP: number | null
  price: number
  status: string
  news: string | null
  warnings: string[]
  components: Record<string, number>
  setPieceDutyChanges: Array<Record<string, unknown>>
}

export type Lineup = {
  gw: number
  formation: string
  starters: number[]
  captain: number
  viceCaptain: number
  bench: number[]
  plannedXP: number
  availabilityAdjustedXP: number
  source: string
}

export type Plan = {
  id: string
  label: string
  state: 'last_official' | 'selected_scenario'
  transferCount: number
  transfersOut: Array<{ element: number; name: string; position: string; selling_price: number }>
  transfersIn: Array<{ element: number; name: string; position: string; purchase_price: number }>
  cashAfter: number | null
  pointsHit: number
  nextFreeTransfers: number
  twoWeekEdge: number
  sixWeekEdge: number
  sixWeekXP: number
  stability: string
  lineup: Lineup
  squad: number[]
  hinge: Array<{
    label: string
    twoWeekDelta: number
    sixWeekDelta: number
    byWeek: Array<{ gw: number; delta: number; source: string }>
  }>
  scored?: boolean
}

export type PlayerPoolEntry = Pick<Player,
  'id' | 'name' | 'fullName' | 'teamId' | 'team' | 'teamShort' | 'position' |
  'price' | 'expectedMinutes' | 'gameweekXP' | 'opponent' | 'home' | 'status' | 'news'
>

export type Fixture = {
  fixtureId: number
  opponent: string
  opponentShort: string
  home: boolean
  kickoff: string | null
  finished: boolean
  score: string | null
  postponed: boolean
  source?: string
  attack?: number
  cleanSheet?: number
}

export type Analysis = {
  schemaVersion: string
  analysisRunId: string
  generatedAt: string
  meta: {
    season: string
    targetGw: number
    deadline: string
    manager: string
    teamName: string
    projectionModel: string
    minutesModel: string
    comparisonPolicy: string
  }
  readiness: {
    state: 'partial' | 'valid'
    previousGw: number
    settledFixtures: number
    totalFixtures: number
    officialDataChecked: boolean
    bookmakerWeeks: number[]
    fallbackWeeks: number[]
    sourceTimes: Record<string, string>
    archives: Record<string, boolean>
    journaled: boolean
    message: string
    uncertainty: string
  }
  current: {
    squad: number[]
    bank: number
    freeTransfers: number
    warning: string
    stateLabel: string
  }
  players: Record<string, Player>
  playerPool: PlayerPoolEntry[]
  plans: Plan[]
  fixtureWall: {
    gameweeks: number[]
    rows: Array<{
      teamId: number
      name: string
      shortName: string
      owned: boolean
      gameweeks: Array<{ gw: number; fixtures: Fixture[] }>
    }>
  }
  experts: {
    targetGw: number
    files: number
    findings: number
    creators: number
    creatorCounts: Record<string, number>
    players: Array<{
      player: string
      positive: number
      negative: number
      neutral: number
      findings: Array<{
        creator: string
        published: string
        category: string
        stance: string
        claim: string
        conviction: string
        videoId: string
      }>
    }>
    state: 'empty' | 'valid'
    emptyMessage: string
  }
  modelForm: {
    resolvedMinutesGameweeks: number[]
    resolvedProjectionArchives: number
    overall: Record<string, unknown>
    byLead: Record<string, unknown>
    byModelVersion: Record<string, unknown>
    state: 'empty' | 'valid'
    emptyMessage: string
  }
  journal: { entries: Array<Record<string, unknown>>; recorded: boolean }
  actions: Record<string, { label: string; updates: string }>
}
