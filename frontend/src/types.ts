export type CompareWeek = {
  gw: number
  xP: number
  blank: boolean
  opponent: string | null
  home: boolean | null
  difficulty: number | null
  source: string | null
}

export type ComparePlayer = {
  id: number
  name: string
  team: string | null
  position: string
  price: number | null
  owned: boolean
  status: string
  news: string | null
  expectedMinutes: number
  ownership: number
  priceOutlook: PriceOutlook | null
  creators: number
  consensus: number
  midweek: number
  gameweeks: CompareWeek[]
}

export type ExpertKind = 'news' | 'read' | 'stat' | 'recommendation' | 'action'
export type ExpertHorizon = 'this_gw' | 'next_few' | 'season'

export type ExpertFinding = {
  creator: string
  published: string
  topic: string | null
  kind: ExpertKind | null
  horizon: ExpertHorizon | null
  stance: 'positive' | 'negative' | 'neutral'
  conviction: string | null
  claim: string
  quote: string | null
  videoId: string
  players: string[]
  teams: string[]
  inferred: string[]
  owned?: boolean
  playerIds?: number[]
}

export type PriceOutlook = {
  element: number
  name: string
  now_cost: number
  percent: number
  hourly_rate: number
  direction: 'rise' | 'fall' | 'flat'
  when: number | null
  likelihood: number
  confident: boolean
  locked_until: string | null
  calibrating: boolean
  projections: Array<{ offset: number; percent: number; likelihood: number }>
}

export type PriceAlert = {
  id: number; name: string; price: number | null
  when: number; direction: 'rise' | 'fall'; percent: number
}

export type ExpertPlayerRow = {
  id: number
  name: string
  team: string | null
  position: string
  price: number | null
  owned: boolean
  status: string
  news: string | null
  positive: number
  negative: number
  neutral: number
  mentions: number
  creators: number
  netStance: number
  support: number
  consensus: number
  modelSignal: number
  disagreement: number
  disagrees: boolean
  affordable?: boolean
  gameweekXP: number | null
  horizonXP: number | null
  expectedMinutes: number | null
  priceOutlook: PriceOutlook | null
  midweek: ExpertFinding[]
  topClaim: ExpertFinding | null
  findings: ExpertFinding[]
}

export type Room = 'gameweek' | 'experts' | 'fixtures' | 'model' | 'compare'

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
  compare: {
    targetGw: number
    gameweeks: number[]
    players: ComparePlayer[]
    minutesNote: string
  }
  experts: {
    targetGw: number
    state: 'empty' | 'valid'
    emptyMessage?: string
    corpus: {
      findings: number
      creators: number
      videos: number
      files: number
      schema?: 'v2' | 'legacy'
      creatorCounts?: Record<string, number>
      publishedFrom?: string | null
      publishedTo?: string | null
      noTopic?: number
      inferredFields?: Record<string, number>
    }
    sections: {
      actNow?: ExpertFinding[]
      squad?: ExpertPlayerRow[]
      targets?: ExpertPlayerRow[]
      fades?: ExpertPlayerRow[]
      captaincy?: {
        creators: ExpertFinding[]
        model: Array<{ id: number; name: string; team: string | null; gameweekXP: number | null }>
      }
      chips?: Array<{ chip: string; findings: ExpertFinding[]; mentions: number; creators: string[] }>
      context?: Array<{ team: string; findings: ExpertFinding[]; mentions: number }>
      creatorActions?: ExpertFinding[]
      priceAlerts?: { owned_falling: PriceAlert[]; target_rising: PriceAlert[] }
    }
    quality?: {
      unresolved: Array<{ name: string; count: number }>
      inferredFields: Record<string, number>
      disagreementThreshold: number
      affordabilityNote: string
    }
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
