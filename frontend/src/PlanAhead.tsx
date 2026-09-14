import { CSSProperties, DragEvent, useDeferredValue, useEffect, useMemo, useState } from 'react'
import { expectedPoints, fixtureLabel, money, signed } from './format'
import { findPlayerForWeek, teamPalette } from './players'
import type { Analysis, PlanDraft, PlanEvaluation, PlanEvaluationWeek, PlanEvent, Player } from './types'

const positionOrder: Player['position'][] = ['GKP', 'DEF', 'MID', 'FWD']

function freshDraft(analysis: Analysis): PlanDraft {
  const gameweeks = analysis.compare.gameweeks
  const wildcardGw = gameweeks.includes(6) ? 6 : null
  return {
    name: wildcardGw ? 'GW6 Wildcard' : `Plan from GW${analysis.meta.targetGw}`,
    baseGw: analysis.meta.targetGw,
    baseAnalysisRunId: analysis.analysisRunId,
    events: wildcardGw ? [{ gw: wildcardGw, chip: 'wildcard', transfers: [] }] : [],
    ideas: [],
  }
}

function editablePlan(plan: PlanDraft): PlanDraft {
  return {
    id: plan.id,
    name: plan.name,
    baseGw: plan.baseGw,
    baseAnalysisRunId: plan.baseAnalysisRunId,
    events: plan.events.map((event) => ({ ...event, transfers: event.transfers.map((move) => ({ ...move })) })),
    ideas: plan.ideas.map((idea) => ({ ...idea })),
    createdAt: plan.createdAt,
    updatedAt: plan.updatedAt,
    lastEvaluation: plan.lastEvaluation,
  }
}

function upsertEvent(events: PlanEvent[], gw: number, change: (event: PlanEvent) => PlanEvent): PlanEvent[] {
  const current = events.find((event) => event.gw === gw) ?? { gw, chip: null, transfers: [] }
  const changed = change(current)
  const other = events.filter((event) => event.gw !== gw)
  return [...other, changed]
    .filter((event) => event.chip || event.transfers.length)
    .sort((a, b) => a.gw - b.gw)
}

async function planRequest(path: 'evaluate' | 'save', plan: PlanDraft) {
  const response = await fetch(`/api/actions/plan/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(plan),
  })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.error ?? `Could not ${path} this plan`)
  return payload
}

export function PlanAheadRoom({ analysis }: { analysis: Analysis }) {
  const [savedPlans, setSavedPlans] = useState<PlanDraft[]>([])
  const [draft, setDraft] = useState<PlanDraft>(() => freshDraft(analysis))
  const [evaluation, setEvaluation] = useState<PlanEvaluation | null>(null)
  const [selectedGw, setSelectedGw] = useState(analysis.compare.gameweeks[0])
  const [outgoingId, setOutgoingId] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [ideaText, setIdeaText] = useState('')
  const [busy, setBusy] = useState<'loading' | 'evaluating' | 'saving' | null>('loading')
  const [message, setMessage] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    let active = true
    void (async () => {
      setBusy('loading')
      setMessage(null)
      try {
        const response = await fetch('/api/plans')
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.error ?? 'Could not load saved plans')
        const plans = payload.plans as PlanDraft[]
        const initial = plans[0] ? editablePlan(plans[0]) : freshDraft(analysis)
        const evaluated = await planRequest('evaluate', initial) as PlanEvaluation
        if (!active) return
        setSavedPlans(plans)
        setDraft(initial)
        setEvaluation(evaluated)
        setSelectedGw(initial.events.find((event) => event.gw >= analysis.meta.targetGw)?.gw ?? analysis.meta.targetGw)
        setDirty(false)
      } catch (reason) {
        if (active) setMessage(reason instanceof Error ? reason.message : 'Could not open Plan Ahead')
      } finally {
        if (active) setBusy(null)
      }
    })()
    return () => { active = false }
  }, [analysis.analysisRunId])

  const selectedWeek = evaluation?.weeks.find((week) => week.gw === selectedGw) ?? evaluation?.weeks[0] ?? null
  const outgoing = outgoingId == null || !selectedWeek?.squad.includes(outgoingId)
    ? null
    : findPlayerForWeek(analysis, outgoingId, selectedGw)
  const candidates = useMemo(() => {
    if (!outgoing || !selectedWeek) return []
    const needle = deferredQuery.trim().toLowerCase()
    return [...analysis.playerPool]
      .filter((player) => player.position === outgoing.position && !selectedWeek.squad.includes(player.id))
      .filter((player) => !needle || `${player.name} ${player.fullName} ${player.team}`.toLowerCase().includes(needle))
      .sort((a, b) => {
        const aWeek = a.gameweeks.find((week) => week.gw === selectedGw)?.xP ?? 0
        const bWeek = b.gameweeks.find((week) => week.gw === selectedGw)?.xP ?? 0
        return bWeek - aWeek || a.price - b.price
      })
      .slice(0, 80)
  }, [analysis.playerPool, deferredQuery, outgoing, selectedGw, selectedWeek])

  const evaluate = async (next: PlanDraft, markDirty = true) => {
    setBusy('evaluating')
    setMessage(null)
    try {
      const current = { ...next, baseAnalysisRunId: analysis.analysisRunId }
      const payload = await planRequest('evaluate', current) as PlanEvaluation
      setDraft(current)
      setEvaluation(payload)
      setDirty(markDirty)
      setOutgoingId(null)
      setQuery('')
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Could not evaluate that change')
    } finally {
      setBusy(null)
    }
  }

  const chooseSaved = (id: string) => {
    const chosen = savedPlans.find((plan) => plan.id === id)
    if (!chosen) return
    const next = editablePlan(chosen)
    setSelectedGw(next.events.find((event) => event.gw >= analysis.meta.targetGw)?.gw ?? analysis.meta.targetGw)
    void evaluate(next, false)
  }

  const startNew = () => {
    const next = freshDraft(analysis)
    setSelectedGw(next.events.find((event) => event.gw >= analysis.meta.targetGw)?.gw ?? analysis.meta.targetGw)
    void evaluate(next, false)
  }

  const duplicate = () => {
    const next = { ...editablePlan(draft), id: null, name: `${draft.name} copy`, createdAt: undefined, updatedAt: undefined }
    void evaluate(next)
  }

  const save = async () => {
    setBusy('saving')
    setMessage(null)
    try {
      const payload = await planRequest('save', { ...draft, baseAnalysisRunId: analysis.analysisRunId }) as {
        plan: PlanDraft; evaluation: PlanEvaluation
      }
      const saved = editablePlan(payload.plan)
      setDraft(saved)
      setEvaluation(payload.evaluation)
      setSavedPlans((plans) => [saved, ...plans.filter((plan) => plan.id !== saved.id)])
      setDirty(false)
      setMessage('Draft saved locally.')
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Could not save this draft')
    } finally {
      setBusy(null)
    }
  }

  const addTransfer = (out: number, incoming: number) => {
    const next = {
      ...draft,
      events: upsertEvent(draft.events, selectedGw, (event) => ({
        ...event,
        transfers: [...event.transfers, { out, in: incoming }],
      })),
    }
    void evaluate(next)
  }

  const removeTransfer = (index: number) => {
    const next = {
      ...draft,
      events: upsertEvent(draft.events, selectedGw, (event) => ({
        ...event,
        transfers: event.transfers.filter((_, moveIndex) => moveIndex !== index),
      })),
    }
    void evaluate(next)
  }

  const toggleWildcard = () => {
    const next = {
      ...draft,
      events: upsertEvent(draft.events, selectedGw, (event) => ({
        ...event,
        chip: event.chip === 'wildcard' ? null : 'wildcard',
      })),
    }
    void evaluate(next)
  }

  const addIdea = () => {
    const text = ideaText.trim()
    if (!text) return
    setDraft((current) => ({
      ...current,
      ideas: [...current.ideas, { id: `idea-${Date.now()}`, gw: selectedGw, text }],
    }))
    setIdeaText('')
    setDirty(true)
  }

  const saveCandidateIdea = (incomingId: number) => {
    const incoming = findPlayerForWeek(analysis, incomingId, selectedGw)
    if (!outgoing || !incoming) return
    setDraft((current) => ({
      ...current,
      ideas: [...current.ideas, {
        id: `idea-${Date.now()}`,
        gw: selectedGw,
        text: `${outgoing.name} → ${incoming.name}`,
      }],
    }))
    setDirty(true)
  }

  const stale = Boolean(draft.id && draft.lastEvaluation?.analysisRunId !== analysis.analysisRunId)
  const selectedEvent = draft.events.find((event) => event.gw === selectedGw)

  return (
    <>
      <div className="room-heading planner-heading">
        <div>
          <span className="eyebrow">Saved routes · current prices assumed</span>
          <h1>Plan ahead</h1>
        </div>
        <div className="draft-controls">
          <label>
            Saved drafts
            <select value={draft.id ?? ''} onChange={(event) => chooseSaved(event.target.value)}>
              <option value="">Unsaved draft</option>
              {savedPlans.map((plan) => <option key={plan.id} value={plan.id ?? ''}>{plan.name}</option>)}
            </select>
          </label>
          <button onClick={startNew} disabled={busy !== null}>New</button>
          <button onClick={duplicate} disabled={busy !== null}>Duplicate</button>
          <button className="action-primary" onClick={() => void save()} disabled={busy !== null || (!dirty && !stale)}>
            {busy === 'saving' ? 'Saving…' : stale ? 'Recalculate & save' : dirty ? 'Save draft' : 'Saved'}
          </button>
        </div>
      </div>

      <section className="draft-nameplate">
        <label>
          Draft name
          <input value={draft.name} maxLength={80} onChange={(event) => { setDraft({ ...draft, name: event.target.value }); setDirty(true) }} />
        </label>
        <div className="draft-score">
          <span>Forecast score</span>
          <strong>{evaluation ? evaluation.netXP.toFixed(1) : '—'}</strong>
          <small>{evaluation ? `${signed(evaluation.edgeVsHold)} vs hold after ${evaluation.totalHits} hit pts` : 'Waiting for evaluation'}</small>
        </div>
        <p className={stale ? 'stale-note' : ''}>
          {stale
            ? 'This saved draft came from an older analysis. The preview uses today’s forecast; save it to adopt the new numbers.'
            : 'Moves cascade into every later week. The model reselects the XI and captain after each change.'}
        </p>
      </section>

      {evaluation && (
        <GameweekRail
          weeks={evaluation.weeks}
          selectedGw={selectedGw}
          onSelect={(gw) => { setSelectedGw(gw); setOutgoingId(null); setQuery('') }}
        />
      )}

      {message && <div className={message.includes('saved') ? 'planner-message success' : 'planner-message'} role="status">{message}</div>}
      {busy === 'loading' && <div className="planner-loading">Loading saved routes…</div>}

      {selectedWeek && (
        <div className="planner-workspace" aria-busy={busy === 'evaluating'}>
          <PlannerPitch
            analysis={analysis}
            week={selectedWeek}
            outgoingId={outgoingId}
            onSelectOutgoing={setOutgoingId}
            onDropPlayer={addTransfer}
          />
          <aside className="planner-editor">
            <header>
              <div><span>Editing</span><h2>GW{selectedGw} moves</h2></div>
              <button className={selectedEvent?.chip === 'wildcard' ? 'chip-on' : ''} onClick={toggleWildcard} disabled={busy !== null}>
                {selectedEvent?.chip === 'wildcard' ? 'Wildcard planned' : 'Plan Wildcard'}
              </button>
            </header>

            <div className="scheduled-moves">
              {(selectedWeek.transfers.length > 0 || selectedWeek.chip) ? (
                <>
                  {selectedWeek.chip && <span className="chip-ticket">Wildcard · free transfers preserved</span>}
                  {selectedWeek.transfers.map((move, index) => (
                    <div className="scheduled-move" key={`${move.out}-${move.in}`}>
                      <span>{move.position}</span><strong>{move.outName}</strong><i>→</i><strong>{move.inName}</strong>
                      <button aria-label={`Remove ${move.outName} to ${move.inName}`} onClick={() => removeTransfer(index)}>×</button>
                    </div>
                  ))}
                </>
              ) : <p>No moves scheduled. Select a shirt on the pitch to explore replacements.</p>}
            </div>

            <section className="replacement-drawer">
              <div className="replacement-title">
                <div><span className="eyebrow">Replacement drawer</span><h3>{outgoing ? `Replace ${outgoing.name}` : 'Choose a shirt on the pitch'}</h3></div>
                {outgoing && <span>{outgoing.position} · {money(outgoing.price)}</span>}
              </div>
              {outgoing ? (
                <>
                  <input
                    className="player-search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={`Search ${outgoing.position} players`}
                    aria-label={`Search ${outgoing.position} replacements`}
                  />
                  <div className="candidate-list">
                    {candidates.map((candidate) => {
                      const week = candidate.gameweeks.find((row) => row.gw === selectedGw)
                      return (
                        <div className="candidate-row" draggable key={candidate.id} onDragStart={(event) => event.dataTransfer.setData('text/player-id', String(candidate.id))}>
                          <button className="candidate-main" onClick={() => addTransfer(outgoing.id, candidate.id)} disabled={busy !== null}>
                            <strong>{candidate.name}</strong><span>{candidate.team} · {money(candidate.price)}</span>
                            <b>{expectedPoints(week?.xP ?? null)}</b><small>{week ? fixtureLabel(week.opponent, week.home) : '—'}</small>
                          </button>
                          <button className="idea-pin" onClick={() => saveCandidateIdea(candidate.id)} title="Keep as a possible move">＋ idea</button>
                        </div>
                      )
                    })}
                  </div>
                  <p className="drag-hint">Click to schedule, or drag a replacement onto any matching shirt.</p>
                </>
              ) : <p className="drawer-empty">The drawer will filter by position and rank the candidates by GW{selectedGw} xP.</p>}
            </section>

            <section className="idea-bench">
              <div><span className="eyebrow">Moves bench</span><h3>Possibilities to remember</h3></div>
              <div className="idea-entry">
                <input value={ideaText} maxLength={300} onChange={(event) => setIdeaText(event.target.value)} placeholder="e.g. Buy if his starting role survives GW5" />
                <button onClick={addIdea}>Keep idea</button>
              </div>
              <ul>
                {draft.ideas.map((idea) => (
                  <li key={idea.id}><span>{idea.gw ? `GW${idea.gw}` : 'Later'}</span><p>{idea.text}</p><button aria-label={`Remove idea ${idea.text}`} onClick={() => { setDraft({ ...draft, ideas: draft.ideas.filter((row) => row.id !== idea.id) }); setDirty(true) }}>×</button></li>
                ))}
                {!draft.ideas.length && <li className="idea-empty">No parked moves yet.</li>}
              </ul>
            </section>
          </aside>
        </div>
      )}

      {evaluation && (
        <details className="planner-assumptions">
          <summary>How this route is scored</summary>
          <ul>{evaluation.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
        </details>
      )}
    </>
  )
}

function GameweekRail({ weeks, selectedGw, onSelect }: { weeks: PlanEvaluationWeek[]; selectedGw: number; onSelect: (gw: number) => void }) {
  return (
    <div className="gameweek-rail" role="tablist" aria-label="Planned gameweeks">
      {weeks.map((week, index) => (
        <button
          key={week.gw}
          className={week.gw === selectedGw ? 'selected' : ''}
          onClick={() => onSelect(week.gw)}
          role="tab"
          aria-selected={week.gw === selectedGw}
        >
          <span>GW{week.gw}</span>
          <strong>{week.lineup.plannedXP.toFixed(1)} xP</strong>
          <small>{week.chip === 'wildcard' ? 'Wildcard' : week.transfers.length ? `${week.transfers.length} move${week.transfers.length === 1 ? '' : 's'}` : 'Roll'}</small>
          <i>{money(week.cash)} · {week.freeTransfersAfter} FT next</i>
          {index < weeks.length - 1 && <b aria-hidden="true">›</b>}
        </button>
      ))}
    </div>
  )
}

function PlannerPitch({
  analysis,
  week,
  outgoingId,
  onSelectOutgoing,
  onDropPlayer,
}: {
  analysis: Analysis
  week: PlanEvaluationWeek
  outgoingId: number | null
  onSelectOutgoing: (id: number) => void
  onDropPlayer: (out: number, incoming: number) => void
}) {
  const players = week.lineup.starters
    .map((id) => findPlayerForWeek(analysis, id, week.gw))
    .filter((player): player is Player => Boolean(player))
  const rows = positionOrder.map((position) => players.filter((player) => player.position === position)).filter((row) => row.length)
  const drop = (event: DragEvent, outgoing: number) => {
    event.preventDefault()
    const incoming = Number(event.dataTransfer.getData('text/player-id'))
    if (incoming) onDropPlayer(outgoing, incoming)
  }
  return (
    <section className="squad-board planning-pitch" aria-label={`Planned GW${week.gw} lineup`}>
      <div className="pitch-title">
        <div><span className="state-ticket">Saved-plan scenario</span><h2>{week.lineup.formation} for GW{week.gw}</h2></div>
        <div className="pitch-score"><strong>{week.lineup.plannedXP.toFixed(1)}</strong><span>planned xP</span></div>
      </div>
      <div className="pitch">
        <div className="centre-circle" aria-hidden="true" />
        {rows.map((row) => (
          <div className="pitch-row" key={row[0].position}>
            {row.map((player) => (
              <PlannerSticker
                key={player.id}
                player={player}
                selected={outgoingId === player.id}
                captain={week.lineup.captain === player.id}
                vice={week.lineup.viceCaptain === player.id}
                onClick={() => onSelectOutgoing(player.id)}
                onDrop={(event) => drop(event, player.id)}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="bench-row">
        <span className="bench-label">Bench</span>
        {week.lineup.bench.map((id, index) => {
          const player = findPlayerForWeek(analysis, id, week.gw)
          return player ? (
            <button
              key={id}
              className={`bench-player ${outgoingId === id ? 'selected-outgoing' : ''}`}
              onClick={() => onSelectOutgoing(id)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => drop(event, id)}
            >
              <small>{index === 0 ? 'GK' : index}</small><strong>{player.name}</strong><span>{fixtureLabel(player.opponent, player.home)} <b>{expectedPoints(player.gameweekXP)}</b></span>
            </button>
          ) : null
        })}
      </div>
    </section>
  )
}

function PlannerSticker({ player, selected, captain, vice, onClick, onDrop }: {
  player: Player; selected: boolean; captain: boolean; vice: boolean
  onClick: () => void; onDrop: (event: DragEvent) => void
}) {
  const [shirt, trim] = teamPalette(player.teamId)
  const style = { '--shirt': shirt, '--trim': trim } as CSSProperties
  return (
    <button
      className={`player-sticker planner-sticker ${selected ? 'selected-outgoing' : ''}`}
      style={style}
      onClick={onClick}
      onDragOver={(event) => event.preventDefault()}
      onDrop={onDrop}
      title="Select this player, or drop a replacement here"
    >
      <span className="shirt" aria-hidden="true"><i>{captain ? 'C' : vice ? 'V' : player.teamShort.slice(0, 1)}</i></span>
      <span className="player-name">{player.name}</span>
      <span className="player-fixture">{fixtureLabel(player.opponent, player.home)}</span>
      <span className="player-xp">{expectedPoints(player.gameweekXP)}</span>
    </button>
  )
}
