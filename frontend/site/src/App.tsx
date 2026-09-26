import { FormEvent, useEffect, useMemo, useState } from "react";

type Week = {
  gw: number;
  xp: number | null;
  fixtures: { opponent: string; home: boolean; difficulty: number | null }[];
};
type Player = {
  id: number;
  name: string;
  club: string;
  clubId: number;
  position: string;
  price: number;
  form: string;
  news: string;
  status: string;
  weeks: Week[];
};
type Pick = {
  id: number;
  position: number;
  multiplier: number;
  captain: boolean;
  vice: boolean;
};
type Moment = {
  kind: string;
  gw: number | null;
  eyebrow: string;
  title: string;
  number: string;
  body: string;
  basis: string;
};
type Team = {
  id: number;
  name: string;
  manager: string;
  points: number;
  rank: number;
};
type Analysis = {
  team: Team;
  lastGw: number | null;
  nextGw: number | null;
  deadline: string | null;
  history: {
    gw: number;
    points: number;
    total: number;
    rank: number;
    bench: number;
  }[];
  squad: Pick[];
  pool: Player[];
  gameweeks: number[];
  freeTransfers: number;
  bank: number | null;
  moments: Moment[];
  projectionTime: string | null;
  squadState: string;
};
type Page = "gameweek" | "planning" | "review";
type Swap = { gw: number; out: number; in: number };

const POSITIONS = ["GKP", "DEF", "MID", "FWD"];
const pages: { id: Page; label: string }[] = [
  { id: "gameweek", label: "My Gameweek" },
  { id: "planning", label: "Plan Ahead" },
  { id: "review", label: "Season in Review" },
];

function teamId(value: string): number | null {
  const trimmed = value.trim();
  const match = trimmed.match(
    /^(?:https?:\/\/fantasy\.premierleague\.com(?:\/[^?#]*)?\/)?entry\/(\d+)(?:[/?#].*)?$/i,
  );
  const number = /^\d{1,9}$/.test(trimmed)
    ? Number(trimmed)
    : match
      ? Number(match[1])
      : null;
  return number && number <= 999_999_999 ? number : null;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok)
    throw new Error(payload.error || "FPL data is temporarily unavailable.");
  return payload as T;
}

const day = (date: string | null) =>
  date
    ? new Intl.DateTimeFormat("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      }).format(new Date(date)) + " UTC"
    : "To be announced";
const number = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("en-GB");
const xp = (value: number | null | undefined) =>
  value == null ? "—" : value.toFixed(1);

function App() {
  const [input, setInput] = useState("");
  const [help, setHelp] = useState(false);
  const [loading, setLoading] = useState<"identity" | "analysis" | null>(null);
  const [identified, setIdentified] = useState<Team | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<Analysis | null>(null);
  const [story, setStory] = useState(false);
  const [storyIndex, setStoryIndex] = useState(0);
  const [page, setPage] = useState<Page>("gameweek");
  const [selectedGw, setSelectedGw] = useState<number | null>(null);
  const [selectedPlayer, setSelectedPlayer] = useState<number | null>(null);
  const [swaps, setSwaps] = useState<Swap[]>([]);
  const [query, setQuery] = useState("");
  const [planError, setPlanError] = useState<string | null>(null);

  const loadTeam = async (id: number, showStory: boolean) => {
    setError(null);
    setLoading("identity");
    setData(null);
    try {
      const found = await getJson<Team>(`/api/public/team/${id}?identity`);
      setIdentified(found);
      setLoading("analysis");
      const payload = await getJson<Analysis>(`/api/public/team/${id}`);
      setData(payload);
      setSelectedGw(payload.nextGw);
      setSwaps(
        JSON.parse(
          localStorage.getItem(`fpl-site-plan-${id}`) || "[]",
        ) as Swap[],
      );
      setStory(
        showStory &&
          !localStorage.getItem(`fpl-site-story-${id}`) &&
          payload.moments.length > 0,
      );
      setStoryIndex(0);
      setPage("gameweek");
      localStorage.setItem("fpl-site-last-team", String(id));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load this team.",
      );
    } finally {
      setLoading(null);
    }
  };

  useEffect(() => {
    const saved = localStorage.getItem("fpl-site-last-team");
    if (saved && teamId(saved)) void loadTeam(Number(saved), false);
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const id = teamId(input);
    if (!id) {
      setError(
        "Enter a team ID or paste a fantasy.premierleague.com team link.",
      );
      return;
    }
    void loadTeam(id, true);
  };

  const finishStory = (destination: Page = "gameweek") => {
    if (!data) return;
    localStorage.setItem(`fpl-site-story-${data.team.id}`, "seen");
    setStory(false);
    setPage(destination);
  };

  const playerMap = useMemo(
    () => new Map(data?.pool.map((player) => [player.id, player]) || []),
    [data],
  );
  const currentGw = selectedGw ?? data?.nextGw ?? null;
  const plannedSquad = useMemo(() => {
    if (!data) return [];
    const ids = data.squad.map((pick) => pick.id);
    for (const swap of swaps
      .filter((move) => currentGw != null && move.gw <= currentGw)
      .sort((a, b) => a.gw - b.gw)) {
      const index = ids.indexOf(swap.out);
      if (index >= 0 && !ids.includes(swap.in)) ids[index] = swap.in;
    }
    return ids;
  }, [data, swaps, currentGw]);
  const changePage = (next: Page) => {
    setPage(next);
    setSelectedPlayer(null);
    setQuery("");
    setPlanError(null);
  };
  const changeWeek = (gw: number) => {
    setSelectedGw(gw);
    changePage("planning");
  };
  const addSwap = (incoming: Player) => {
    if (!data || selectedPlayer == null || currentGw == null) return;
    const outgoing = playerMap.get(selectedPlayer);
    if (
      !outgoing ||
      outgoing.position !== incoming.position ||
      plannedSquad.includes(incoming.id)
    )
      return;
    const clubs = plannedSquad.map((id) => playerMap.get(id)?.clubId);
    if (
      clubs.filter((club) => club === incoming.clubId).length >= 3 &&
      outgoing.clubId !== incoming.clubId
    ) {
      setPlanError(`Your draft already has three ${incoming.club} players.`);
      return;
    }
    const next = [
      ...swaps,
      { gw: currentGw, out: outgoing.id, in: incoming.id },
    ];
    setSwaps(next);
    localStorage.setItem(`fpl-site-plan-${data.team.id}`, JSON.stringify(next));
    setSelectedPlayer(null);
    setQuery("");
    setPlanError(null);
  };
  const clearPlan = () => {
    if (!data) return;
    setSwaps([]);
    localStorage.removeItem(`fpl-site-plan-${data.team.id}`);
    setSelectedPlayer(null);
  };

  if (!data)
    return (
      <div className="arrival">
        <div className="arrival-grid" aria-hidden="true" />
        <header className="arrival-header">
          <span className="logo">
            P<span>⋆</span>ITCH
          </span>
          <span>YOUR SEASON. YOUR NEXT MOVE.</span>
        </header>
        <main className="arrival-main">
          <div className="arrival-badge">
            THE WHOLE SEASON, IN YOUR HANDS <span>✦</span>
          </div>
          <h1>
            Every point
            <br />
            has a <em>story.</em>
          </h1>
          <p>
            Step inside your FPL season. Relive the calls that shaped it, then
            make your next one count.
          </p>
          <form onSubmit={submit} className="entry-form">
            <label htmlFor="team-id">YOUR FPL TEAM ID</label>
            <div className="entry-row">
              <input
                id="team-id"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="e.g. 8837120"
                disabled={!!loading}
                inputMode="numeric"
                autoComplete="off"
              />
              <button type="submit" disabled={!!loading}>
                {loading ? "Reading your season…" : "Explore my team"}{" "}
                <span>↗</span>
              </button>
            </div>
          </form>
          <button
            type="button"
            className="help-link"
            onClick={() => setHelp(!help)}
            aria-expanded={help}
          >
            Where do I find my team ID? <span>{help ? "−" : "+"}</span>
          </button>
          {help && (
            <div className="help-box">
              Open your team on the official FPL website. The number after{" "}
              <strong>/entry/</strong> in the address is your ID. You can paste
              the whole team link here, too.
              <code>
                fantasy.premierleague.com/entry/<mark>8837120</mark>/event/5
              </code>
            </div>
          )}
          {loading && (
            <div className="loading-status" role="status">
              <span className="pulse-ball" />
              <div>
                <strong>
                  {loading === "identity"
                    ? "Finding your team in the official FPL record…"
                    : `Found ${identified?.name}. Building your season…`}
                </strong>
                {loading === "analysis" && (
                  <div className="loading-stages" aria-label="Analysis underway">
                    <span>GAMEWEEK RECORD</span>
                    <span>TRANSFER REPLAY</span>
                    <span>FUTURE FIXTURES</span>
                  </div>
                )}
              </div>
            </div>
          )}
          {error && (
            <div className="entry-error" role="alert">
              {error}
            </div>
          )}
          <div className="arrival-foot">
            <span>01 / LOOK BACK</span>
            <span>02 / MANAGE NOW</span>
            <span>03 / PLAN AHEAD</span>
          </div>
        </main>
        <div className="arrival-orb" aria-hidden="true">
          <div className="orb-inner">
            GW<span>26</span>
          </div>
        </div>
      </div>
    );

  const weekRows = [
    ...data.history.map((row) => ({ gw: row.gw, past: true })),
    ...data.gameweeks.map((gw) => ({ gw, past: false })),
  ];
  const card = data.moments[storyIndex];

  return (
    <div className="site-shell">
      <header className="site-header">
        <button
          className="logo"
          onClick={() => {
            setStory(false);
            changePage("gameweek");
          }}
        >
          P<span>⋆</span>ITCH
        </button>
        <nav aria-label="Main navigation">
          {pages.map((item) => (
            <button
              key={item.id}
              className={page === item.id && !story ? "selected" : ""}
              onClick={() => {
                setStory(false);
                changePage(item.id);
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="team-pill">
          <span className="team-dot" />
          {data.team.name}
          <button
            aria-label="Change team"
            title="Change team"
            onClick={() => {
              setData(null);
              setStory(false);
              setInput("");
              localStorage.removeItem("fpl-site-last-team");
            }}
          >
            ↗
          </button>
        </div>
      </header>
      <div className="season-rail" aria-label="Season timeline">
        <span className="rail-label">26 / 27 SEASON</span>
        <div className="rail-scroll">
          {weekRows.map(({ gw, past }) => (
            <button
              key={gw}
              className={`${past ? "past" : "future"} ${gw === (story ? card?.gw : page === "planning" ? currentGw : data.nextGw) ? "active" : ""}`}
              onClick={() =>
                past ? (setStory(false), changePage("review")) : changeWeek(gw)
              }
            >
              <small>
                {past ? "PLAYED" : gw === data.nextGw ? "NEXT" : "AHEAD"}
              </small>
              GW{gw}
            </button>
          ))}
        </div>
        <span className="rail-end">◉</span>
      </div>

      {story && card ? (
        <main className="story-view">
          <div className="story-top">
            <span>
              YOUR SEASON / CHAPTER {String(storyIndex + 1).padStart(2, "0")}
            </span>
            <button onClick={() => finishStory()}>
              Skip to my gameweek ↗
            </button>
          </div>
          <div className="story-progress">
            {data.moments.map((moment, index) => (
              <button
                key={index}
                className={index === storyIndex ? "active" : ""}
                aria-label={`Go to story ${index + 1}: ${moment.title}`}
                onClick={() => setStoryIndex(index)}
              />
            ))}
          </div>
          <article className={`story-card ${card.kind}`} key={storyIndex}>
            <div className="story-meta">
              <span>{card.eyebrow}</span>
              <span>{card.gw ? `GW${card.gw}` : "SEASON SO FAR"}</span>
            </div>
            <div className="story-content">
              <h1>{card.title}</h1>
              <div className="story-number">{card.number}</div>
              <p>{card.body}</p>
              <small>{card.basis}</small>
            </div>
            <div className="story-mark" aria-hidden="true">
              ✦
            </div>
          </article>
          <div className="story-controls">
            <button
              disabled={storyIndex === 0}
              onClick={() => setStoryIndex((index) => index - 1)}
            >
              ← Previous
            </button>
            <span>
              {storyIndex + 1} / {data.moments.length}
            </span>
            {storyIndex < data.moments.length - 1 ? (
              <button
                className="button-main"
                onClick={() => setStoryIndex((index) => index + 1)}
              >
                Next story →
              </button>
            ) : (
              <div className="story-exit">
                <button onClick={() => finishStory("planning")}>
                  Explore plans
                </button>
                <button className="button-main" onClick={() => finishStory()}>
                  Manage my gameweek →
                </button>
              </div>
            )}
          </div>
        </main>
      ) : (
        <main className="content">
          {page === "gameweek" && (
            <>
              <section className="page-head">
                <div>
                  <span className="eyebrow">
                    THE PRESENT / GW{data.nextGw ?? "—"}
                  </span>
                  <h1>
                    Make the next
                    <br />
                    <em>move count.</em>
                  </h1>
                  <p>
                    {data.team.name} · {data.squadState}
                  </p>
                </div>
                <div className="deadline-card">
                  <span>NEXT DEADLINE</span>
                  <strong>{day(data.deadline)}</strong>
                  <small>
                    {data.freeTransfers} free transfers banked · £
                    {data.bank?.toFixed(1) ?? "—"}m in the bank
                  </small>
                </div>
              </section>
              <div className="main-grid">
                <Squad
                  data={data}
                  ids={data.squad.map((pick) => pick.id)}
                  playerMap={playerMap}
                  gw={data.nextGw}
                />
                <div className="side-stack">
                  <section className="panel">
                    <span className="eyebrow">THIS WEEK'S BASELINE</span>
                    <h2>Start with your squad.</h2>
                    <p>
                      Your last confirmed team is the starting point. We can see
                      public picks saved at the previous deadline; changes since
                      then will appear after the next deadline.
                    </p>
                    <div className="big-metric">
                      <strong>
                        {xp(
                          lineupXp(
                            data.squad.map((pick) => pick.id),
                            data.squad,
                            playerMap,
                            data.nextGw,
                          ),
                        )}
                      </strong>
                      <span>
                        projected XI points
                        <br />
                        including saved captain
                      </span>
                    </div>
                    <small className="model-note">
                      {data.projectionTime
                        ? `Model updated ${day(data.projectionTime)}. Forecasts are estimates.`
                        : "Current-gameweek model projections are unavailable."}
                    </small>
                  </section>
                  <CaptainBoard data={data} playerMap={playerMap} />
                  <button
                    className="plan-callout"
                    onClick={() => changePage("planning")}
                  >
                    <span>THE FUTURE / PLAN AHEAD</span>
                    <strong>What if you changed the squad?</strong>
                    <small>
                      Shop players, compare future fixtures and keep a draft.
                    </small>
                    <b>Open planning board ↗</b>
                  </button>
                </div>
              </div>
            </>
          )}

          {page === "planning" && (
            <>
              <section className="page-head">
                <div>
                  <span className="eyebrow">THE FUTURE / PLAN AHEAD</span>
                  <h1>
                    Try the move.
                    <br />
                    <em>See the path.</em>
                  </h1>
                  <p>
                    Pick a gameweek, select someone on the pitch, and shop a
                    replacement.
                  </p>
                </div>
                <div className="deadline-card">
                  <span>YOUR DRAFT</span>
                  <strong>{swaps.length} transfer ideas</strong>
                  <small>Saved in this browser for {data.team.name}</small>
                </div>
              </section>
              <div className="week-tabs" aria-label="Plan gameweek">
                {data.gameweeks.map((gw) => (
                  <button
                    key={gw}
                    className={currentGw === gw ? "active" : ""}
                    onClick={() => {
                      setSelectedGw(gw);
                      setSelectedPlayer(null);
                    }}
                  >
                    GW{gw}
                  </button>
                ))}
              </div>
              <div className="planning-grid">
                <div>
                  <Squad
                    data={data}
                    ids={plannedSquad}
                    playerMap={playerMap}
                    gw={currentGw}
                    selected={selectedPlayer}
                    onSelect={setSelectedPlayer}
                  />
                  <p className="plan-caveat">
                    Draft only. Current prices are shown, but selling prices,
                    budget legality and transfer hits are not yet checked. The
                    saved captain slot follows a replacement. No changes are
                    sent to FPL.
                  </p>
                </div>
                <div className="side-stack">
                  <section className="panel">
                    <span className="eyebrow">GW{currentGw} COMPARISON</span>
                    <h2>
                      {swaps.length
                        ? "Your draft versus hold"
                        : "Build your first idea"}
                    </h2>
                    <div className="comparison">
                      <div>
                        <small>HOLD XI</small>
                        <strong>
                          {xp(
                            lineupXp(
                              data.squad.map((pick) => pick.id),
                              data.squad,
                              playerMap,
                              currentGw,
                            ),
                          )}
                        </strong>
                      </div>
                      <div>
                        <small>DRAFT XI</small>
                        <strong>
                          {xp(
                            lineupXp(
                              plannedSquad,
                              data.squad,
                              playerMap,
                              currentGw,
                            ),
                          )}
                        </strong>
                      </div>
                    </div>
                    <small className="model-note">
                      Projected points for the saved XI and captain slot.
                      Transfer hits and selling prices are excluded.
                    </small>
                    {swaps.length > 0 && (
                      <>
                        <div className="swap-list">
                          {swaps.map((move, index) => (
                            <div key={index}>
                              <span>
                                GW{move.gw} · {playerMap.get(move.out)?.name} →{" "}
                                {playerMap.get(move.in)?.name}
                              </span>
                            </div>
                          ))}
                        </div>
                        <button className="text-button" onClick={clearPlan}>
                          Clear this draft
                        </button>
                      </>
                    )}
                  </section>
                  <section className="panel shopping">
                    <span className="eyebrow">PLAYER MARKET</span>
                    <h2>
                      {selectedPlayer
                        ? `Replace ${playerMap.get(selectedPlayer)?.name}`
                        : "Select a player on the pitch"}
                    </h2>
                    {planError && <p className="plan-error" role="alert">{planError}</p>}
                    {selectedPlayer && (
                      <>
                        <input
                          className="search"
                          placeholder="Search players or clubs"
                          aria-label="Search players or clubs"
                          value={query}
                          onChange={(event) => setQuery(event.target.value)}
                        />
                        <div className="market-list">
                          {data.pool
                            .filter(
                              (player) =>
                                player.position ===
                                  playerMap.get(selectedPlayer)?.position &&
                                !plannedSquad.includes(player.id) &&
                                `${player.name} ${player.club}`
                                  .toLowerCase()
                                  .includes(query.toLowerCase()),
                            )
                            .sort(
                              (a, b) =>
                                (b.weeks.find((week) => week.gw === currentGw)
                                  ?.xp ?? -1) -
                                (a.weeks.find((week) => week.gw === currentGw)
                                  ?.xp ?? -1),
                            )
                            .slice(0, 25)
                            .map((player) => (
                              <button
                                key={player.id}
                                onClick={() => addSwap(player)}
                              >
                                <span>
                                  <strong>{player.name}</strong>
                                  <small>
                                    {player.club} · £{player.price.toFixed(1)}m
                                  </small>
                                </span>
                                <span className="market-xp">
                                  {xp(
                                    player.weeks.find(
                                      (week) => week.gw === currentGw,
                                    )?.xp,
                                  )}{" "}
                                  xP
                                </span>
                              </button>
                            ))}
                        </div>
                      </>
                    )}
                  </section>
                </div>
              </div>
            </>
          )}

          {page === "review" && (
            <>
              <section className="page-head">
                <div>
                  <span className="eyebrow">THE PAST / SEASON IN REVIEW</span>
                  <h1>
                    The season
                    <br />
                    <em>so far.</em>
                  </h1>
                  <p>
                    {data.team.name} · {number(data.team.points)} points ·
                    overall rank {number(data.team.rank)}
                  </p>
                </div>
                <button
                  className="replay-button"
                  onClick={() => {
                    setStoryIndex(0);
                    setStory(true);
                  }}
                >
                  Replay the story ↗
                </button>
              </section>
              <div className="review-grid">
                <section className="panel chart-panel">
                  <span className="eyebrow">THE GAMEWEEK RECORD</span>
                  <h2>Every week adds a chapter.</h2>
                  <div className="bar-chart">
                    {data.history.map((row) => (
                      <div key={row.gw} className="bar-column">
                        <span>{row.points}</span>
                        <div
                          style={{
                            height: `${Math.max(12, (row.points / Math.max(...data.history.map((item) => item.points))) * 160)}px`,
                          }}
                        />
                        <small>GW{row.gw}</small>
                      </div>
                    ))}
                  </div>
                  <p>
                    Official settled gameweek points. Tap a story card for the
                    decision behind a moment.
                  </p>
                </section>
                <div className="moment-list">
                  {data.moments.map((moment, index) => (
                    <button
                      className={`moment-tile ${moment.kind}`}
                      key={index}
                      onClick={() => {
                        setStoryIndex(index);
                        setStory(true);
                      }}
                    >
                      <small>
                        {moment.eyebrow} /{" "}
                        {moment.gw ? `GW${moment.gw}` : "SEASON"}
                      </small>
                      <strong>{moment.title}</strong>
                      <b>{moment.number}</b>
                      <span>Explore this moment ↗</span>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </main>
      )}
      <footer className="site-footer">
        <span>P⋆ITCH / YOUR SEASON. YOUR NEXT MOVE.</span>
        <span>Public FPL data · read only · unofficial prototype</span>
      </footer>
    </div>
  );
}

function lineupXp(
  ids: number[],
  picks: Pick[],
  players: Map<number, Player>,
  gw: number | null,
): number | null {
  if (gw == null) return null;
  const starters = ids.slice(0, 11);
  const values = starters.map(
    (id) => players.get(id)?.weeks.find((week) => week.gw === gw)?.xp,
  );
  if (values.some((value) => value == null)) return null;
  const captainSlot = picks.findIndex((pick) => pick.captain);
  const captain =
    captainSlot >= 0 && captainSlot < 11 ? ids[captainSlot] : null;
  if (captain == null) return null;
  return (
    values.reduce<number>((sum, value) => sum + (value ?? 0), 0) +
    (players.get(captain ?? -1)?.weeks.find((week) => week.gw === gw)?.xp ?? 0)
  );
}

function Squad({
  data,
  ids,
  playerMap,
  gw,
  selected,
  onSelect,
}: {
  data: Analysis;
  ids: number[];
  playerMap: Map<number, Player>;
  gw: number | null;
  selected?: number | null;
  onSelect?: (id: number) => void;
}) {
  const starters = ids.slice(0, 11);
  const bench = ids.slice(11);
  const captainSlot = data.squad.findIndex((pick) => pick.captain);
  const captainId = captainSlot >= 0 ? ids[captainSlot] : null;
  return (
    <section className="pitch-panel">
      <div className="pitch-panel-head">
        <div>
          <span className="eyebrow">
            {onSelect ? "YOUR WHAT-IF SQUAD" : data.squadState}
          </span>
          <h2>{onSelect ? `Draft for GW${gw}` : `Looking towards GW${gw}`}</h2>
        </div>
        <span>15 PLAYER SQUAD</span>
      </div>
      <div className="pitch-surface">
        <div className="pitch-line" />
        <div className="pitch-circle" />
        {POSITIONS.map((position) => (
          <div className="formation-row" key={position}>
            {starters
              .filter((id) => playerMap.get(id)?.position === position)
              .map((id) => (
                <PlayerCard
                  key={id}
                  player={playerMap.get(id)!}
                  gw={gw}
                  captain={captainId === id}
                  selected={selected === id}
                  onClick={onSelect ? () => onSelect(id) : undefined}
                />
              ))}
          </div>
        ))}
      </div>
      <div className="bench-row">
        <span>BENCH</span>
        {bench
          .map((id) => playerMap.get(id))
          .filter((player): player is Player => !!player)
          .map((player) => (
            <PlayerCard
              key={player.id}
              player={player}
              gw={gw}
              selected={selected === player.id}
              onClick={onSelect ? () => onSelect(player.id) : undefined}
            />
          ))}
      </div>
    </section>
  );
}

function PlayerCard({
  player,
  gw,
  captain,
  selected,
  onClick,
}: {
  player: Player;
  gw: number | null;
  captain?: boolean;
  selected?: boolean;
  onClick?: () => void;
}) {
  const week = player.weeks.find((item) => item.gw === gw);
  const fixture =
    week?.fixtures
      .map((item) => `${item.opponent} (${item.home ? "H" : "A"})`)
      .join(" + ") || "No fixture";
  return (
    <button
      type="button"
      className={`player-card ${selected ? "selected" : ""}`}
      onClick={onClick}
      disabled={!onClick}
      title={`${player.name} · ${fixture}${player.news ? ` · ${player.news}` : ""}`}
    >
      <div className="player-shirt">{player.club.slice(0, 3)}</div>
      <strong>
        {player.name}
        {captain && <i>C</i>}
      </strong>
      <span>{fixture}</span>
      <b>{xp(week?.xp)} xP</b>
    </button>
  );
}

function CaptainBoard({
  data,
  playerMap,
}: {
  data: Analysis;
  playerMap: Map<number, Player>;
}) {
  const captains = data.squad
    .slice(0, 11)
    .map((pick) => ({ pick, player: playerMap.get(pick.id) }))
    .filter((item): item is { pick: Pick; player: Player } => !!item.player)
    .sort(
      (a, b) =>
        (b.player.weeks.find((week) => week.gw === data.nextGw)?.xp ?? -1) -
        (a.player.weeks.find((week) => week.gw === data.nextGw)?.xp ?? -1),
    )
    .slice(0, 3);
  return (
    <section className="panel captain-panel">
      <span className="eyebrow">ARMBAND WATCH</span>
      <h2>Captain candidates</h2>
      {captains.map((item, index) => (
        <div className="captain-row" key={item.player.id}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <strong>{item.player.name}</strong>
          <small>{item.player.club}</small>
          <b>
            {xp(item.player.weeks.find((week) => week.gw === data.nextGw)?.xp)}{" "}
            xP
          </b>
        </div>
      ))}
      <small className="model-note">
        Ranked by this gameweek's player forecast. Captain choice remains yours.
      </small>
    </section>
  );
}

export default App;
