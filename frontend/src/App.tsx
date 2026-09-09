import { CSSProperties, FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { deadlineLabel, expectedPoints, fixtureLabel, money, signed, sourceLabel } from './format'
import type { Analysis, ExpertFinding, ExpertPlayerRow, Fixture, Plan, Player, PlayerPoolEntry, Room } from './types'

const rooms: Array<{ id: Room; label: string; number: string }> = [
  { id: 'gameweek', label: 'My gameweek', number: '01' },
  { id: 'experts', label: 'Expert room', number: '02' },
  { id: 'fixtures', label: 'Fixture wall', number: '03' },
  { id: 'model', label: 'Model form', number: '04' },
]

const positionOrder: Player['position'][] = ['GKP', 'DEF', 'MID', 'FWD']

function teamPalette(teamId: number): [string, string] {
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

function poolPlayer(player: PlayerPoolEntry): Player {
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

function findPlayer(analysis: Analysis, id: number): Player | undefined {
  return analysis.players[String(id)] ?? (() => {
    const player = analysis.playerPool.find((row) => row.id === id)
    return player ? poolPlayer(player) : undefined
  })()
}

function App() {
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [room, setRoom] = useState<Room>('gameweek')
  const [selectedPlanId, setSelectedPlanId] = useState('hold')
  const [customPlan, setCustomPlan] = useState<Plan | null>(null)
  const [selectedPlayer, setSelectedPlayer] = useState<number | null>(null)
  const [action, setAction] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  const load = async () => {
    try {
      const response = await fetch('/api/analysis')
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error ?? 'Could not load the current analysis')
      setAnalysis(payload)
      setCustomPlan(null)
      setSelectedPlanId('hold')
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load the current analysis')
    }
  }

  useEffect(() => { void load() }, [])

  const runAction = async (name: 'refresh' | 'rebuild') => {
    if (!analysis || action) return
    setAction(name)
    setActionMessage(null)
    try {
      const response = await fetch(`/api/actions/${name}`, { method: 'POST' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error ?? `${name} failed`)
      setAnalysis(payload.analysis)
      setCustomPlan(null)
      setSelectedPlanId('hold')
      setActionMessage(name === 'refresh' ? 'Official data and feeds refreshed.' : 'Comparisons rebuilt without archiving.')
    } catch (reason) {
      setActionMessage(reason instanceof Error ? reason.message : `${name} failed`)
    } finally {
      setAction(null)
    }
  }

  if (!analysis) {
    return (
      <main className="boot-state">
        <span className="boot-ball" aria-hidden="true">◆</span>
        <h1>FPL Decision Room</h1>
        <p>{error ?? 'Laying out the squad board…'}</p>
        {error && <button onClick={() => void load()}>Try again</button>}
      </main>
    )
  }

  const selectedPlan = selectedPlanId === 'custom' && customPlan
    ? customPlan
    : analysis.plans.find((plan) => plan.id === selectedPlanId) ?? analysis.plans[0]
  const player = selectedPlayer == null ? null : findPlayer(analysis, selectedPlayer)

  return (
    <div className="app-shell">
      <header className="masthead">
        <button className="brand" onClick={() => setRoom('gameweek')}>
          <span className="brand-mark">FPL</span>
          <span>Decision<br />Room</span>
        </button>
        <nav aria-label="Decision room">
          {rooms.map((item) => (
            <button
              key={item.id}
              className={room === item.id ? 'active' : ''}
              onClick={() => setRoom(item.id)}
              aria-current={room === item.id ? 'page' : undefined}
            >
              <small>{item.number}</small>{item.label}
            </button>
          ))}
        </nav>
        <div className="header-actions">
          <button title={analysis.actions.refresh.updates} disabled={action !== null} onClick={() => void runAction('refresh')}>
            {action === 'refresh' ? 'Refreshing…' : 'Refresh data'}
          </button>
          <button className="action-primary" title={analysis.actions.rebuild.updates} disabled={action !== null} onClick={() => void runAction('rebuild')}>
            {action === 'rebuild' ? 'Rebuilding…' : 'Rebuild comparisons'}
          </button>
        </div>
      </header>

      <ReadinessRibbon analysis={analysis} />
      {actionMessage && <div className="action-message" role="status">{actionMessage}</div>}

      <main className={`room room-${room}`}>
        {room === 'gameweek' && (
          <GameweekRoom
            analysis={analysis}
            selectedPlan={selectedPlan}
            onSelectPlan={setSelectedPlanId}
            onSelectPlayer={setSelectedPlayer}
            onAnalysis={setAnalysis}
            customPlan={customPlan}
            onCustomPlan={(plan) => { setCustomPlan(plan); setSelectedPlanId('custom') }}
          />
        )}
        {room === 'experts' && <ExpertRoom analysis={analysis} selectedPlan={selectedPlan} onSelectPlayer={setSelectedPlayer} />}
        {room === 'fixtures' && <FixtureWall analysis={analysis} selectedPlan={selectedPlan} />}
        {room === 'model' && <ModelForm analysis={analysis} />}
      </main>

      <footer className="run-footer">
        <span>Analysis run <code>{analysis.analysisRunId}</code></span>
        <span>{analysis.meta.projectionModel}</span>
        <span>Local only · no FPL account writes</span>
      </footer>

      {player && <PlayerDrawer player={player} onClose={() => setSelectedPlayer(null)} />}
    </div>
  )
}

function ReadinessRibbon({ analysis }: { analysis: Analysis }) {
  const { readiness, meta, current, experts } = analysis
  const allArchived = Object.values(readiness.archives).every(Boolean)
  return (
    <section className={`readiness ${readiness.state}`} aria-label="Analysis readiness">
      <div className="deadline-stamp">
        <span>Gameweek {meta.targetGw}</span>
        <strong>{deadlineLabel(meta.deadline)}</strong>
      </div>
      <div className="readiness-stat">
        <span>Free transfers</span><strong>{current.freeTransfers}</strong>
      </div>
      <div className="readiness-stat">
        <span>In the bank</span><strong>{money(current.bank)}</strong>
      </div>
      <div className="readiness-copy">
        <span className="status-dot" />
        <strong>{readiness.message}</strong>
        <small>Market: GW{readiness.bookmakerWeeks.join('–')} · fallback: GW{readiness.fallbackWeeks.join('–')}</small>
      </div>
      <div className="readiness-stat compact">
        <span>Expert corpus</span><strong>{experts.corpus.findings ? `${experts.corpus.findings} findings` : 'Not started'}</strong>
      </div>
      <div className="readiness-stat compact">
        <span>Freeze</span><strong>{allArchived ? 'Recorded' : 'Pending'}</strong>
      </div>
    </section>
  )
}

function GameweekRoom({
  analysis,
  selectedPlan,
  onSelectPlan,
  onSelectPlayer,
  onAnalysis,
  customPlan,
  onCustomPlan,
}: {
  analysis: Analysis
  selectedPlan: Plan
  onSelectPlan: (id: string) => void
  onSelectPlayer: (id: number) => void
  onAnalysis: (analysis: Analysis) => void
  customPlan: Plan | null
  onCustomPlan: (plan: Plan) => void
}) {
  const [journalOpen, setJournalOpen] = useState(false)
  return (
    <>
      <div className="gameweek-heading room-heading">
        <div>
          <span className="eyebrow">{analysis.meta.teamName}</span>
          <h1>Set the board for GW{analysis.meta.targetGw}</h1>
        </div>
        <p>{analysis.readiness.uncertainty}</p>
      </div>
      <div className="gameweek-grid">
        <SquadPitch analysis={analysis} plan={selectedPlan} onSelectPlayer={onSelectPlayer} />
        <OptionsBoard analysis={analysis} selectedPlan={selectedPlan} customPlan={customPlan} onSelectPlan={onSelectPlan} onCustomPlan={onCustomPlan} />
      </div>
      <DecisionStrip analysis={analysis} plan={selectedPlan} onOpenJournal={() => setJournalOpen(true)} />
      {journalOpen && (
        <JournalForm
          analysis={analysis}
          plan={selectedPlan}
          onClose={() => setJournalOpen(false)}
          onRecorded={onAnalysis}
        />
      )}
    </>
  )
}

function SquadPitch({ analysis, plan, onSelectPlayer }: { analysis: Analysis; plan: Plan; onSelectPlayer: (id: number) => void }) {
  const players = plan.lineup.starters.map((id) => findPlayer(analysis, id)).filter((player): player is Player => Boolean(player))
  const rows = positionOrder.map((position) => players.filter((player) => player.position === position)).filter((row) => row.length)
  return (
    <section className="squad-board" aria-label={`${plan.label} lineup`}>
      <div className="pitch-title">
        <div>
          <span className="state-ticket">{plan.state === 'last_official' ? 'Last official squad' : 'Selected scenario'}</span>
          <h2>{plan.lineup.formation} for GW{plan.lineup.gw}</h2>
        </div>
        <div className="pitch-score"><strong>{plan.scored === false ? '—' : plan.lineup.plannedXP.toFixed(1)}</strong><span>{plan.scored === false ? 'unscored preview' : 'planned xP'}</span></div>
      </div>
      <div className="pitch">
        <div className="centre-circle" aria-hidden="true" />
        {rows.map((row) => (
          <div className="pitch-row" key={row[0].position}>
            {row.map((player) => (
              <PlayerSticker
                key={player.id}
                player={player}
                captain={plan.lineup.captain === player.id}
                vice={plan.lineup.viceCaptain === player.id}
                onClick={() => onSelectPlayer(player.id)}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="bench-row">
        <span className="bench-label">Bench</span>
        {plan.lineup.bench.map((id, index) => {
          const player = findPlayer(analysis, id)
          return player ? (
            <button key={id} className="bench-player" onClick={() => onSelectPlayer(id)}>
              <small>{index === 0 ? 'GK' : index}</small><strong>{player.name}</strong><span>{fixtureLabel(player.opponent, player.home)} <b>{expectedPoints(player.gameweekXP)}</b></span>
            </button>
          ) : null
        })}
      </div>
    </section>
  )
}

function PlayerSticker({ player, captain, vice, onClick }: { player: Player; captain: boolean; vice: boolean; onClick: () => void }) {
  const [shirt, trim] = teamPalette(player.teamId)
  const style = { '--shirt': shirt, '--trim': trim } as CSSProperties
  return (
    <button className={`player-sticker ${player.warnings.length ? 'flagged' : ''}`} style={style} onClick={onClick}>
      <span className="shirt" aria-hidden="true"><i>{captain ? 'C' : vice ? 'V' : player.teamShort.slice(0, 1)}</i></span>
      <span className="player-name">{player.name}</span>
      <span className="player-fixture">{fixtureLabel(player.opponent, player.home)}</span>
      <span className="player-xp">{expectedPoints(player.gameweekXP)}</span>
      {player.warnings.length > 0 && <span className="warning-pin" title={player.warnings.join(' · ')}>!</span>}
    </button>
  )
}

function OptionsBoard({ analysis, selectedPlan, customPlan, onSelectPlan, onCustomPlan }: { analysis: Analysis; selectedPlan: Plan; customPlan: Plan | null; onSelectPlan: (id: string) => void; onCustomPlan: (plan: Plan) => void }) {
  return (
    <aside className="options-board">
      <header>
        <div><span className="eyebrow">Shortlist</span><h2>Options worth comparing</h2></div>
        <span className="candidate-note">{analysis.meta.comparisonPolicy.startsWith('Independent') ? 'independent searches' : 'same candidate set'}</span>
      </header>
      <div className="option-columns" aria-hidden="true">
        <span>Move</span><span>2 GW</span><span>6 GW</span><span>Cash</span>
      </div>
      <div className="options-list">
        {analysis.plans.map((plan, index) => (
          <button key={plan.id} className={`option-row ${selectedPlan.id === plan.id ? 'selected' : ''}`} onClick={() => onSelectPlan(plan.id)}>
            <span className="option-rank">{String(index + 1).padStart(2, '0')}</span>
            <span className="option-move">
              <strong>{plan.label}</strong>
              <small>{plan.transferCount ? `${plan.transferCount} transfer${plan.transferCount === 1 ? '' : 's'} · ${plan.pointsHit ? `−${plan.pointsHit} hit` : 'no hit'}` : 'Bank a transfer'} · {plan.stability}</small>
            </span>
            <strong className={plan.twoWeekEdge > 0 ? 'positive' : ''}>{plan.scored === false ? '—' : signed(plan.twoWeekEdge)}</strong>
            <strong className={plan.sixWeekEdge > 0 ? 'positive' : ''}>{plan.scored === false ? '—' : signed(plan.sixWeekEdge)}</strong>
            <span>{money(plan.cashAfter)}</span>
          </button>
        ))}
      </div>
      <div className="comparison-footnote">
        <span className="market-key" /> GW{analysis.readiness.bookmakerWeeks.join('–')} market-backed
        <span className="fallback-key" /> GW{analysis.readiness.fallbackWeeks.join('–')} fallback
      </div>
      <WhatIfBuilder analysis={analysis} customPlan={customPlan} onPreview={onCustomPlan} onSelect={() => onSelectPlan('custom')} />
      <Hinge plan={selectedPlan} />
    </aside>
  )
}

function WhatIfBuilder({ analysis, customPlan, onPreview, onSelect }: { analysis: Analysis; customPlan: Plan | null; onPreview: (plan: Plan) => void; onSelect: () => void }) {
  const hold = analysis.plans[0]
  const [open, setOpen] = useState(false)
  const [outId, setOutId] = useState<number>(hold.squad[0])
  const outgoing = findPlayer(analysis, outId)
  const candidates = analysis.playerPool.filter((player) => player.position === outgoing?.position && !hold.squad.includes(player.id))
  const [inId, setInId] = useState<number | null>(null)

  useEffect(() => { setInId(candidates[0]?.id ?? null) }, [outId])

  const preview = () => {
    if (!outgoing || inId == null) return
    const incoming = analysis.playerPool.find((player) => player.id === inId)
    if (!incoming) return
    const replace = (ids: number[]) => ids.map((id) => id === outId ? inId : id)
    onPreview({
      ...hold,
      id: 'custom',
      label: `${outgoing.name} → ${incoming.name}`,
      state: 'selected_scenario',
      transferCount: 1,
      transfersOut: [{ element: outId, name: outgoing.name, position: outgoing.position, selling_price: 0 }],
      transfersIn: [{ element: inId, name: incoming.name, position: incoming.position, purchase_price: incoming.price }],
      cashAfter: null,
      pointsHit: 0,
      nextFreeTransfers: Math.min(analysis.current.freeTransfers, 5),
      twoWeekEdge: 0,
      sixWeekEdge: 0,
      sixWeekXP: 0,
      stability: 'Unscored preview',
      scored: false,
      squad: replace(hold.squad),
      lineup: {
        ...hold.lineup,
        starters: replace(hold.lineup.starters),
        bench: replace(hold.lineup.bench),
        captain: hold.lineup.captain === outId ? inId : hold.lineup.captain,
        viceCaptain: hold.lineup.viceCaptain === outId ? inId : hold.lineup.viceCaptain,
        plannedXP: 0,
        availabilityAdjustedXP: 0,
        source: 'unscored_preview',
      },
      hinge: [],
    })
  }

  return (
    <section className="what-if">
      <button className="what-if-toggle" onClick={() => setOpen((value) => !value)}><span>＋</span><strong>Try your own swap</strong><small>local · ephemeral · unscored</small></button>
      {open && <div className="what-if-editor">
        <label>Out<select value={outId} onChange={(event) => setOutId(Number(event.target.value))}>{hold.squad.map((id) => { const player = findPlayer(analysis, id); return player ? <option key={id} value={id}>{player.name} · {player.position}</option> : null })}</select></label>
        <span>→</span>
        <label>In<select value={inId ?? ''} onChange={(event) => setInId(Number(event.target.value))}>{candidates.map((player) => <option key={player.id} value={player.id}>{player.name} · {player.team} · {money(player.price)}</option>)}</select></label>
        <button onClick={preview} disabled={inId == null}>Preview on pitch</button>
      </div>}
      {customPlan && <button className="custom-recall" onClick={onSelect}>Custom preview: <strong>{customPlan.label}</strong></button>}
    </section>
  )
}

function Hinge({ plan }: { plan: Plan }) {
  if (!plan.hinge.length) {
    return (
      <section className="hinge empty-hinge">
        <span className="eyebrow">Why it moves</span>
        <p>{plan.scored === false ? 'This free-form swap is a visual preview only. Rebuild through the Python model before comparing its xP.' : 'Hold is the baseline. Select an alternative to see which swaps and gameweeks create its edge.'}</p>
      </section>
    )
  }
  const max = Math.max(1, ...plan.hinge.flatMap((row) => row.byWeek.map((week) => Math.abs(week.delta))))
  return (
    <section className="hinge">
      <span className="eyebrow">Why it moves</span>
      {plan.hinge.map((row) => (
        <div className="hinge-group" key={row.label}>
          <div className="hinge-title"><strong>{row.label}</strong><span>{signed(row.sixWeekDelta)} xP</span></div>
          <div className="contribution-bars">
            {row.byWeek.map((week) => (
              <div className="bar-slot" key={week.gw} title={`GW${week.gw}: ${signed(week.delta)} · ${sourceLabel(week.source)}`}>
                <span className={week.source === 'bookmaker' ? 'market' : 'fallback'} style={{ height: `${Math.max(3, Math.abs(week.delta) / max * 38)}px` }} />
                <small>{week.gw}</small>
              </div>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}

function DecisionStrip({ analysis, plan, onOpenJournal }: { analysis: Analysis; plan: Plan; onOpenJournal: () => void }) {
  const archiveCount = Object.values(analysis.readiness.archives).filter(Boolean).length
  return (
    <section className="decision-strip">
      <div className="check"><span className="check-icon good">✓</span><span><strong>Squad legal</strong><small>{plan.lineup.formation} · captain and vice in XI</small></span></div>
      <div className="check"><span className="check-icon pending">{archiveCount}/3</span><span><strong>Freeze {archiveCount === 3 ? 'complete' : 'pending'}</strong><small>Scheduler owns immutable archives</small></span></div>
      <div className="check"><span className="check-icon pending">!</span><span><strong>No measured margin</strong><small>Raw leaders are comparisons</small></span></div>
      <button className="record-button" onClick={onOpenJournal} disabled={analysis.journal.recorded || plan.scored === false}>
        {analysis.journal.recorded ? 'Decision recorded' : plan.scored === false ? 'Rebuild before recording' : 'Review & record decision'}
      </button>
    </section>
  )
}

function JournalForm({ analysis, plan, onClose, onRecorded }: { analysis: Analysis; plan: Plan; onClose: () => void; onRecorded: (analysis: Analysis) => void }) {
  const runnerUp = analysis.plans.find((item) => item.id !== plan.id) ?? analysis.plans[0]
  const [reasoning, setReasoning] = useState('')
  const [caseAgainst, setCaseAgainst] = useState('')
  const [confidence, setConfidence] = useState('medium')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const response = await fetch('/api/actions/journal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gw: analysis.meta.targetGw,
          category: plan.id === 'hold' ? 'hold' : 'transfer',
          recommendation: plan.label,
          reasoning,
          confidence,
          caseAgainst,
          runnerUp: runnerUp.label,
          runnerUpDelta: plan.sixWeekEdge - runnerUp.sixWeekEdge,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error ?? 'Journal write failed')
      onRecorded(payload.analysis)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Journal write failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="journal-form" onSubmit={(event) => void submit(event)}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="Close">×</button>
        <span className="eyebrow">Local journal · GW{analysis.meta.targetGw}</span>
        <h2>Record the choice, not just the outcome</h2>
        <div className="journal-matchup">
          <div><small>Recommendation</small><strong>{plan.label}</strong></div>
          <span>vs</span>
          <div><small>Runner-up</small><strong>{runnerUp.label}</strong></div>
        </div>
        <label>Why this leads now<textarea required value={reasoning} onChange={(event) => setReasoning(event.target.value)} placeholder="Use only information available before the deadline." /></label>
        <label>What could make it wrong<textarea value={caseAgainst} onChange={(event) => setCaseAgainst(event.target.value)} placeholder="Minutes, late news, fallback fixtures, or a judgment call…" /></label>
        <label>Confidence<select value={confidence} onChange={(event) => setConfidence(event.target.value)}><option>low</option><option>medium</option><option>high</option></select></label>
        {error && <p className="form-error">{error}</p>}
        <div className="form-actions"><button type="button" onClick={onClose}>Cancel</button><button className="action-primary" disabled={saving}>{saving ? 'Recording…' : 'Append to journal'}</button></div>
      </form>
    </div>
  )
}

const KIND_LABEL: Record<string, string> = {
  news: 'news', read: 'eye test', stat: 'stat', recommendation: 'advice', action: 'own team',
}
const HORIZON_LABEL: Record<string, string> = {
  this_gw: 'this GW', next_few: 'next few', season: 'season',
}

function num(value: number | null | undefined, places = 1) {
  return value == null ? '—' : value.toFixed(places)
}

/** A signed consensus, drawn from the centre so direction reads before magnitude. */
function StanceBar({ value, raw, support }: { value: number; raw: number; support: number }) {
  const width = Math.min(50, Math.abs(value) * 50)
  return (
    <span className="stance-bar" title={`net stance ${raw.toFixed(2)}, spoken by ${Math.round(support * 100)}% of the creators in this corpus`}>
      <span className="stance-bar-axis" />
      <span
        className={value < 0 ? 'stance-bar-fill negative' : 'stance-bar-fill positive'}
        style={value < 0 ? { right: '50%', width } : { left: '50%', width }}
      />
    </span>
  )
}

function KindTag({ finding }: { finding: ExpertFinding }) {
  const kind = finding.kind ?? 'read'
  const uncertain = finding.inferred?.includes('kind')
  return (
    <span className={`kind-tag kind-${kind}`} title={uncertain ? 'kind inferred by fallback, not by rule' : undefined}>
      {KIND_LABEL[kind] ?? kind}{uncertain && <sup className="kind-inferred">?</sup>}
    </span>
  )
}

function ClaimLine({ finding }: { finding: ExpertFinding }) {
  return (
    <li className={`claim-line stance-${finding.stance}`}>
      <KindTag finding={finding} />
      <span className="claim-creator">{finding.creator}</span>
      <span className="claim-text">{finding.claim}</span>
      {finding.horizon && <span className="claim-horizon">{HORIZON_LABEL[finding.horizon]}</span>}
    </li>
  )
}

type ColumnSet = 'squad' | 'market'

function ExpertTable({
  rows, columns, onSelectPlayer, emptyLabel,
}: {
  rows: ExpertPlayerRow[]
  columns: ColumnSet
  onSelectPlayer: (id: number) => void
  emptyLabel: string
}) {
  if (!rows.length) return <p className="section-empty">{emptyLabel}</p>
  return (
    <div className="expert-table-wrap">
      <table className="expert-table">
        <thead>
          <tr>
            <th className="col-player">Player</th>
            <th>Pos</th>
            <th className="num">£</th>
            {columns === 'market' && <th className="num" title="Affordable from the bank plus your most expensive player in this position, at current price">Fits</th>}
            <th className="num" title="Model expected points this gameweek">xP</th>
            <th className="num" title="Model expected points over six gameweeks">6GW</th>
            <th className="num" title="Creators mentioning this player">Say</th>
            <th className="col-stance" title="Net stance weighted by conviction, then scaled by how many of the corpus's creators actually discussed him">Consensus</th>
            <th className="num" title="Model rank within position, rescaled to -1..1">Model</th>
            <th className="num" title="Consensus minus model. Negative: the model rates him higher than the creators do.">&Delta;</th>
            <th className="col-claim">Sharpest claim</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={row.disagrees ? 'row-disagrees' : undefined}
              onClick={() => onSelectPlayer(row.id)}
              tabIndex={0}
              onKeyDown={(event) => event.key === 'Enter' && onSelectPlayer(row.id)}
            >
              <td className="col-player">
                <strong>{row.name}</strong>
                <span className="row-team">{row.team}</span>
                {row.status !== 'a' && <span className="row-flag" title={row.news ?? 'flagged'}>!</span>}
              </td>
              <td>{row.position}</td>
              <td className="num">{money(row.price)}</td>
              {columns === 'market' && (
                <td className="num">{row.affordable ? <span className="fits-yes">yes</span> : <span className="fits-no">no</span>}</td>
              )}
              <td className="num">{num(row.gameweekXP)}</td>
              <td className="num strong">{num(row.horizonXP)}</td>
              <td className="num">{row.mentions ? `${row.creators}/${row.mentions}` : '—'}</td>
              <td className="col-stance">
                {row.mentions ? <StanceBar value={row.consensus} raw={row.netStance} support={row.support} /> : <span className="no-coverage">no coverage</span>}
              </td>
              <td className="num">{num(row.modelSignal, 2)}</td>
              <td className={`num ${row.disagrees ? 'delta-flag' : ''}`}>{row.mentions ? num(row.disagreement, 2) : '—'}</td>
              <td className="col-claim">
                {row.topClaim ? (
                  <>
                    <KindTag finding={row.topClaim} />
                    <span className={`claim-text stance-${row.topClaim.stance}`}>{row.topClaim.claim}</span>
                  </>
                ) : (
                  <span className="no-coverage">nobody discussed him this week</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ExpertSection({ n, title, note, children }: { n: string; title: string; note?: string; children: ReactNode }) {
  return (
    <section className="expert-section">
      <header><span className="section-number">{n}</span><h2>{title}</h2>{note && <p>{note}</p>}</header>
      {children}
    </section>
  )
}

function ExpertRoom({ analysis, selectedPlan, onSelectPlayer }: { analysis: Analysis; selectedPlan: Plan; onSelectPlayer: (id: number) => void }) {
  const { corpus, sections, quality } = analysis.experts
  const relevant = new Set([
    ...selectedPlan.transfersIn.map((row) => row.name),
    ...selectedPlan.lineup.starters.map((id) => analysis.players[String(id)]?.name),
  ])

  if (analysis.experts.state === 'empty') {
    return (
      <>
        <div className="room-heading expert-heading">
          <div><span className="eyebrow">Creator evidence</span><h1>Expert room</h1></div>
        </div>
        <section className="expert-empty">
          <div className="empty-microphones" aria-hidden="true"><span /><span /><span /></div>
          <span className="state-ticket">Corpus empty for this gameweek</span>
          <h2>{analysis.experts.emptyMessage}</h2>
          <p>The room will group extracted claims by decision and keep dissent visible. It will not turn repeated opinions into a synthetic score.</p>
          <div className="affected-list"><strong>First players to watch</strong>{[...relevant].filter(Boolean).slice(0, 6).map((name) => <span key={name}>{name}</span>)}</div>
        </section>
      </>
    )
  }

  const inferredKind = corpus.inferredFields?.kind ?? 0
  const inferredHere = (sections.actNow ?? []).filter((f) => f.inferred?.includes('kind')).length

  return (
    <>
      <div className="room-heading expert-heading">
        <div><span className="eyebrow">Creator evidence · GW{analysis.experts.targetGw}</span><h1>Expert room</h1></div>
      </div>

      <div className="corpus-strip">
        <div><strong>{corpus.findings}</strong><span>findings</span></div>
        <div><strong>{corpus.creators}</strong><span>creators</span></div>
        <div><strong>{corpus.videos}</strong><span>videos</span></div>
        <div><strong>{corpus.publishedTo ?? '—'}</strong><span>latest</span></div>
        <div className="corpus-warn"><strong>{inferredKind}</strong><span>kind inferred, not stated</span></div>
      </div>

      <ExpertSection
        n="01"
        title="Act on this"
        note={`Reported news and eye-test reads dated to this deadline, about a player you own or could realistically buy — the claims the model cannot produce for itself. ${inferredHere} of these ${(sections.actNow ?? []).length} carry a kind the migration inferred rather than the extractor stating it, and are ranked last; treat them as weaker.`}
      >
        <ul className="act-list">
          {(sections.actNow ?? []).map((finding, i) => (
            <li key={`${finding.videoId}-${i}`} className={`act-row stance-${finding.stance}`}>
              <KindTag finding={finding} />
              <span className="owned-tag">{finding.owned ? 'owned' : ''}</span>
              <span className="act-players">{finding.players.map((p) => p.split(' (')[0]).join(', ') || '—'}</span>
              <span className="act-claim">{finding.claim}</span>
              <span className="act-meta">{finding.creator} · {finding.conviction}</span>
            </li>
          ))}
          {!(sections.actNow ?? []).length && <li className="section-empty">Nothing this week that the model cannot already see.</li>}
        </ul>
      </ExpertSection>

      <ExpertSection
        n="02"
        title="Your squad"
        note="Worst combined view first — creator consensus and model rank together. A highlighted Δ means the two disagree; that row is worth reading before you sell."
      >
        <ExpertTable rows={sections.squad ?? []} columns="squad" onSelectPlayer={onSelectPlayer} emptyLabel="No squad rows." />
      </ExpertSection>

      <ExpertSection n="03" title="Targets" note={`Discussed positively and not owned. ${quality?.affordabilityNote ?? ''}`}>
        <ExpertTable rows={(sections.targets ?? []).slice(0, 25)} columns="market" onSelectPlayer={onSelectPlayer} emptyLabel="No positively discussed players outside the squad." />
      </ExpertSection>

      <ExpertSection n="04" title="Avoid and fade" note="Negative consensus — including players you own. Check here before buying into something the creators already flagged.">
        <ExpertTable rows={(sections.fades ?? []).slice(0, 20)} columns="market" onSelectPlayer={onSelectPlayer} emptyLabel="Nobody was argued against this week." />
      </ExpertSection>

      <ExpertSection n="05" title="Captaincy" note="Creator picks beside your own model's top expected points this gameweek.">
        <div className="captain-split">
          <div>
            <h3>What they said</h3>
            <ul className="claim-list">
              {(sections.captaincy?.creators ?? []).map((finding, i) => <ClaimLine key={`${finding.videoId}-${i}`} finding={finding} />)}
              {!(sections.captaincy?.creators ?? []).length && <li className="section-empty">No captaincy claims for this gameweek.</li>}
            </ul>
          </div>
          <div>
            <h3>Model top five</h3>
            <table className="expert-table compact">
              <tbody>
                {(sections.captaincy?.model ?? []).map((row, i) => (
                  <tr key={row.id} onClick={() => onSelectPlayer(row.id)}>
                    <td className="num rank">{i + 1}</td>
                    <td><strong>{row.name}</strong> <span className="row-team">{row.team}</span></td>
                    <td className="num strong">{num(row.gameweekXP)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </ExpertSection>

      <ExpertSection n="06" title="Chips" note="What the creators are planning, and when. Long-range windows live here rather than in the sections above.">
        <div className="chip-grid">
          {(sections.chips ?? []).map((chip) => (
            <article key={chip.chip} className="chip-block">
              <header><h3>{chip.chip}</h3><span>{chip.mentions} claims · {chip.creators.join(', ')}</span></header>
              <ul className="claim-list">{chip.findings.slice(0, 6).map((finding, i) => <ClaimLine key={`${finding.videoId}-${i}`} finding={finding} />)}</ul>
            </article>
          ))}
          {!(sections.chips ?? []).length && <p className="section-empty">No chip discussion in this corpus.</p>}
        </div>
      </ExpertSection>

      <ExpertSection n="07" title="Team and league context" note="Claims about a club rather than a player. Read these against the fixture wall.">
        <div className="context-grid">
          {(sections.context ?? []).slice(0, 8).map((row) => (
            <article key={row.team} className="context-block">
              <h3>{row.team}</h3>
              <ul className="claim-list">{row.findings.slice(0, 4).map((finding, i) => <ClaimLine key={`${finding.videoId}-${i}`} finding={finding} />)}</ul>
            </article>
          ))}
          {!(sections.context ?? []).length && <p className="section-empty">No team-level claims extracted.</p>}
        </div>
      </ExpertSection>

      <ExpertSection n="08" title="What they actually did" note="Their own teams, not their advice. Revealed preference is a different signal from a recommendation.">
        <ul className="claim-list two-col">
          {(sections.creatorActions ?? []).slice(0, 24).map((finding, i) => <ClaimLine key={`${finding.videoId}-${i}`} finding={finding} />)}
          {!(sections.creatorActions ?? []).length && <li className="section-empty">No own-team statements extracted.</li>}
        </ul>
      </ExpertSection>

      <details className="expert-quality">
        <summary>09 · Extraction quality — {quality?.unresolved.length ?? 0} unresolved names, {corpus.noTopic ?? 0} untopiced findings</summary>
        <p>
          Findings whose <code>kind</code> was inferred by fallback rather than stated: {inferredKind} of {corpus.findings}.
          Horizon inferred: {corpus.inferredFields?.horizon ?? 0}. Corpus schema: {corpus.schema}.
          Migrated rows carry weaker horizons than freshly extracted ones; treat the timeframe as a hint, not a fact.
        </p>
        <ul className="unresolved-list">
          {(quality?.unresolved ?? []).map((row) => <li key={row.name}><span className="num">{row.count}&times;</span> {row.name}</li>)}
          {!(quality?.unresolved ?? []).length && <li>Every name in this corpus resolved to the roster.</li>}
        </ul>
      </details>
    </>
  )
}

function FixtureWall({ analysis, selectedPlan }: { analysis: Analysis; selectedPlan: Plan }) {
  const [view, setView] = useState<'fixtures' | 'attack' | 'defence'>('fixtures')
  const [selected, setSelected] = useState<{ team: string; gw: number; fixture: Fixture } | null>(null)
  const wall = useRef<HTMLDivElement>(null)
  const scenarioTeams = new Set(selectedPlan.squad.map((id) => findPlayer(analysis, id)?.teamId))

  useEffect(() => {
    if (wall.current) wall.current.scrollLeft = Math.max(0, (analysis.meta.targetGw - 2) * 72)
  }, [analysis.meta.targetGw])

  const heat = (fixture: Fixture): CSSProperties => {
    if (fixture.finished || view === 'fixtures') return {}
    const value = view === 'attack' ? fixture.attack : fixture.cleanSheet
    if (value == null) return {}
    const normalized = view === 'attack' ? Math.max(0, Math.min(1, (value - 0.6) / 2)) : Math.max(0, Math.min(1, (value - 0.1) / 0.5))
    return { backgroundColor: `rgba(53, 168, 107, ${0.08 + normalized * 0.46})` }
  }

  return (
    <>
      <div className="room-heading fixture-heading">
        <div><span className="eyebrow">20 clubs · 38 gameweeks</span><h1>Fixture wall</h1></div>
        <div className="segmented" aria-label="Fixture metric">
          {(['fixtures', 'attack', 'defence'] as const).map((item) => <button key={item} className={view === item ? 'active' : ''} onClick={() => setView(item)}>{item[0].toUpperCase() + item.slice(1)}</button>)}
        </div>
      </div>
      <div className="fixture-legend">
        <span>UPPERCASE = home</span><span>lowercase = away</span><span className="owned-key">● owned club</span>
        {view !== 'fixtures' && <span>fixed {view === 'attack' ? '0.6–2.6 xG' : '10–60% clean-sheet'} scale · future only</span>}
      </div>
      <div className="fixture-scroll" ref={wall}>
        <table className="fixture-table">
          <thead><tr><th>Club</th>{analysis.fixtureWall.gameweeks.map((gw) => <th key={gw} className={gw === analysis.meta.targetGw ? 'now-column' : ''}>GW{gw}</th>)}</tr></thead>
          <tbody>
            {analysis.fixtureWall.rows.map((row) => (
              <tr key={row.teamId} className={scenarioTeams.has(row.teamId) ? 'scenario-team' : ''}>
                <th><span className="club-dot" style={{ background: teamPalette(row.teamId)[0] }} />{row.name}{row.owned && <i title="Owned club">●</i>}</th>
                {row.gameweeks.map((cell) => (
                  <td key={cell.gw} className={cell.gw === analysis.meta.targetGw ? 'now-column' : ''}>
                    {cell.fixtures.length ? cell.fixtures.map((fixture) => (
                      <button
                        key={fixture.fixtureId}
                        className={`${fixture.finished ? 'past-fixture' : 'future-fixture'} ${cell.fixtures.length > 1 ? 'double' : ''}`}
                        style={heat(fixture)}
                        title={`${row.name} vs ${fixture.opponent} · ${fixture.home ? 'home' : 'away'}${fixture.source ? ` · ${sourceLabel(fixture.source)}` : ''}`}
                        onClick={() => setSelected({ team: row.name, gw: cell.gw, fixture })}
                      >
                        {fixture.postponed ? 'P' : fixture.finished && view === 'fixtures' && fixture.score ? fixture.score : fixture.home ? fixture.opponentShort.toUpperCase() : fixture.opponentShort.toLowerCase()}
                      </button>
                    )) : <span className="blank">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="fixture-inspector">
        {selected ? (
          <><strong>{selected.team} · GW{selected.gw}</strong><span>{selected.fixture.opponent} {selected.fixture.home ? 'at home' : 'away'}</span>{selected.fixture.attack != null && <span>{selected.fixture.attack.toFixed(2)} team xG</span>}{selected.fixture.cleanSheet != null && <span>{Math.round(selected.fixture.cleanSheet * 100)}% clean sheet</span>}<em>{selected.fixture.source ? sourceLabel(selected.fixture.source) : selected.fixture.finished ? 'Settled result' : 'No forecast yet'}</em></>
        ) : <span>Select a fixture cell to inspect its venue, forecast and source.</span>}
      </div>
    </>
  )
}

function ModelForm({ analysis }: { analysis: Analysis }) {
  return (
    <>
      <div className="room-heading model-heading">
        <div><span className="eyebrow">Forecast record</span><h1>Model form</h1></div>
        <div className="model-versions"><span>{analysis.meta.minutesModel}</span><span>{analysis.meta.projectionModel}</span></div>
      </div>
      {analysis.modelForm.state === 'empty' ? (
        <section className="model-empty">
          <div className="empty-chart" aria-hidden="true"><i /><i /><i /><i /><i /><i /></div>
          <span className="state-ticket">No resolved forecast window</span>
          <h2>{analysis.modelForm.emptyMessage}</h2>
          <p>The honest chart is empty. Once forecasts resolve, this room starts with minutes MAE, signed bias, Brier score and log loss—not a confidence badge.</p>
          <div className="milestone-track">
            <div className="reached"><strong>Now</strong><span>Archive one untouched forecast</span></div>
            <div><strong>1 GW</strong><span>First error inspection</span></div>
            <div><strong>6 GWs</strong><span>Early margin estimate</span></div>
            <div><strong>Nov</strong><span>Useful trend begins</span></div>
          </div>
        </section>
      ) : (
        <section className="model-results">
          <div><span className="eyebrow">Independent samples</span><strong>{analysis.modelForm.resolvedMinutesGameweeks.length}</strong><p>resolved minutes gameweeks</p></div>
          <div><span className="eyebrow">Projection windows</span><strong>{analysis.modelForm.resolvedProjectionArchives}</strong><p>completed archives</p></div>
          <pre>{JSON.stringify(analysis.modelForm.overall, null, 2)}</pre>
        </section>
      )}
      <aside className="shadow-boundary"><strong>Shadow challengers live here only.</strong><span>They are excluded at the analysis-adapter boundary and cannot affect squad options.</span></aside>
    </>
  )
}

function PlayerDrawer({ player, onClose }: { player: Player; onClose: () => void }) {
  const components = Object.entries(player.components).filter(([, value]) => Math.abs(value) >= 0.01).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  return (
    <aside className="player-drawer" aria-label={`${player.name} detail`}>
      <button className="drawer-close" onClick={onClose} aria-label="Close player details">×</button>
      <div className="drawer-shirt" style={{ '--shirt': teamPalette(player.teamId)[0], '--trim': teamPalette(player.teamId)[1] } as CSSProperties}><span>{player.teamShort}</span></div>
      <span className="eyebrow">{player.team} · {player.position}</span>
      <h2>{player.fullName || player.name}</h2>
      <p className="drawer-fixture">GW fixture: {fixtureLabel(player.opponent, player.home)}</p>
      <div className="drawer-numbers"><div><strong>{player.expectedMinutes?.toFixed(0) ?? '—'}</strong><span>expected min</span></div><div><strong>{player.gameweekXP?.toFixed(1) ?? '—'}</strong><span>gameweek xP</span></div><div><strong>{money(player.price)}</strong><span>current price</span></div></div>
      {player.minutesBands && <div className="minutes-band"><span style={{ width: `${player.minutesBands.p_zero * 100}%` }}>0</span><span style={{ width: `${player.minutesBands.p_1_59 * 100}%` }}>1–59</span><span style={{ width: `${player.minutesBands.p_60_plus * 100}%` }}>60+</span></div>}
      {player.warnings.length > 0 && <div className="drawer-warning"><strong>Needs attention</strong>{player.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
      <h3>Scoring components</h3>
      <div className="component-list">{components.map(([name, value]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{signed(value)}</strong></div>)}</div>
      <p className="drawer-note">Availability-adjusted xP remains a sensitivity. This drawer shows the live forecast only.</p>
    </aside>
  )
}

export default App
