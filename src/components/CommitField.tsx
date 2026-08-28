import { useEffect, useMemo, useState } from 'react';

const GITHUB_USERNAMES = [
  'gingur',
  'trhinehart-attentive',
  'trhinehart-godaddy',
  'gingur-driver',
  'gingur-bot',
] as const;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

type Day = { date: string; count: number; level: number };
type UserResponse = { contributions: Day[] };
type ContributionData = { days: Day[]; total: number; accounts: number };

function contributionLevel(count: number, quartiles: [number, number, number]) {
  if (count === 0) return 0;
  if (count > quartiles[2]) return 4;
  if (count > quartiles[1]) return 3;
  if (count > quartiles[0]) return 2;
  return 1;
}

function quartiles(values: number[]): [number, number, number] {
  if (values.length === 0) return [0, 0, 0];
  const sorted = [...values].sort((a, b) => a - b);
  const at = (amount: number) => {
    const position = (sorted.length - 1) * amount;
    const base = Math.floor(position);
    const remainder = position - base;
    return sorted[base]! + remainder * ((sorted[base + 1] ?? sorted[base]!) - sorted[base]!);
  };
  return [at(0.25), at(0.5), at(0.75)];
}

async function loadContributions(signal: AbortSignal): Promise<ContributionData> {
  const responses = await Promise.allSettled(
    GITHUB_USERNAMES.map(async (username) => {
      const response = await fetch(
        `https://github-contributions-api.jogruber.de/v4/${encodeURIComponent(username)}?y=last`,
        { signal },
      );
      if (!response.ok) throw new Error(`Unable to load ${username}`);
      return (await response.json()) as UserResponse;
    }),
  );

  const merged = new Map<string, number>();
  const successful = responses.filter(
    (result): result is PromiseFulfilledResult<UserResponse> => result.status === 'fulfilled',
  );

  for (const response of successful) {
    for (const day of response.value.contributions) {
      merged.set(day.date, (merged.get(day.date) ?? 0) + day.count);
    }
  }

  if (successful.length === 0) throw new Error('No contribution accounts were available');

  const counts = [...merged.values()].filter((count) => count > 0);
  const thresholds = quartiles(counts);
  const days = [...merged.entries()]
    .map(([date, count]) => ({ date, count, level: contributionLevel(count, thresholds) }))
    .sort((a, b) => a.date.localeCompare(b.date));

  return {
    days,
    total: days.reduce((sum, day) => sum + day.count, 0),
    accounts: successful.length,
  };
}

function formatDate(date: string) {
  return new Date(`${date}T00:00:00`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export default function CommitField() {
  const [data, setData] = useState<ContributionData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    loadContributions(controller.signal)
      .then(setData)
      .catch((loadError: unknown) => {
        if (loadError instanceof DOMException && loadError.name === 'AbortError') return;
        setError(true);
      });
    return () => controller.abort();
  }, []);

  const weeks = useMemo(() => {
    if (!data?.days.length) return [];
    const firstDay = new Date(`${data.days[0]!.date}T00:00:00`).getDay();
    const padded: Array<Day | null> = [...Array<null>(firstDay).fill(null), ...data.days];
    const grouped: Array<Array<Day | null>> = [];
    for (let index = 0; index < padded.length; index += 7) {
      grouped.push(padded.slice(index, index + 7));
    }
    return grouped;
  }, [data]);

  return (
    <div className="commit-field">
      <div className="commit-orbits" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>

      <header className="commit-field-meta">
        <div>
          <span className="commit-badge" aria-hidden="true">
            GH
          </span>
          <p>
            <span>Combined activity</span>Rolling 12 months
          </p>
        </div>
        {data && (
          <p className="commit-total" aria-live="polite">
            <strong>{data.total.toLocaleString()}</strong> contributions · {data.accounts}{' '}
            identities
          </p>
        )}
      </header>

      {error && <p className="commit-message">The contribution signal is temporarily offline.</p>}

      {!data && !error && (
        <div className="commit-loading" aria-label="Loading combined GitHub contribution activity">
          {Array.from({ length: 196 }, (_, index) => (
            <i className={index % 11 === 0 || index % 17 === 0 ? 'is-active' : ''} key={index} />
          ))}
        </div>
      )}

      {data && (
        <div className="commit-scroll">
          <div className="commit-calendar">
            <div className="commit-months" aria-hidden="true">
              {weeks.map((week, index) => {
                const current = week.find((day): day is Day => day !== null);
                const previous = weeks[index - 1]?.find((day): day is Day => day !== null);
                const month = current ? new Date(`${current.date}T00:00:00`).getMonth() : -1;
                const previousMonth = previous
                  ? new Date(`${previous.date}T00:00:00`).getMonth()
                  : -1;
                return <span key={index}>{month !== previousMonth ? MONTHS[month] : ''}</span>;
              })}
            </div>

            <div
              className="commit-weeks"
              role="img"
              aria-label={`${data.total.toLocaleString()} GitHub contributions across ${data.accounts} identities over the last year`}
            >
              {weeks.map((week, weekIndex) => (
                <div className="commit-week" key={weekIndex}>
                  {Array.from({ length: 7 }, (_, dayIndex) => {
                    const day = week[dayIndex];
                    return day ? (
                      <i
                        className={`commit-dot level-${day.level}`}
                        key={day.date}
                        title={`${day.count} contribution${day.count === 1 ? '' : 's'} on ${formatDate(day.date)}`}
                      />
                    ) : (
                      <i className="commit-dot is-empty" key={dayIndex} />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="commit-legend">
        <span>Five accounts · one signal</span>
        <span className="legend-scale" aria-hidden="true">
          Less <i className="level-0" />
          <i className="level-1" />
          <i className="level-2" />
          <i className="level-3" />
          <i className="level-4" /> More
        </span>
      </div>
    </div>
  );
}
