export function money(tenths: number | null | undefined): string {
  return tenths == null ? '—' : `£${(tenths / 10).toFixed(1)}m`
}

export function signed(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}`
}

export function fixtureLabel(opponent: string, home: boolean | null | undefined): string {
  if (home == null) return opponent
  return `${opponent} ${home ? '(H)' : '(A)'}`
}

export function deadlineLabel(value: string): string {
  const date = new Date(value)
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/London',
    timeZoneName: 'short',
  }).format(date)
}

export function sourceLabel(source: string): string {
  return source === 'bookmaker' ? 'Market' : 'Fallback'
}
