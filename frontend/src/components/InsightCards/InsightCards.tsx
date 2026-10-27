import {
  Liveline,
  type LivelinePoint,
  type LivelineSeries,
} from "liveline";
import {
  useEffect,
  useMemo,
  useState,
  type ComponentType,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import styles from "./InsightCards.module.css";

const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

const formatPercent = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const formatMoney = (v: number) =>
  `$${Math.round(v).toLocaleString("en-US")}`;

function makePoints(values: number[], gap = 6): LivelinePoint[] {
  const end = Math.floor(Date.now() / 1000);
  return values.map((value, index) => ({
    time: end - (values.length - 1 - index) * gap,
    value,
  }));
}

function smooth(values: number[], perSegment = 9): number[] {
  if (values.length < 3) return values.slice();
  const out: number[] = [];
  const n = values.length;
  for (let i = 0; i < n - 1; i += 1) {
    const p0 = values[Math.max(0, i - 1)];
    const p1 = values[i];
    const p2 = values[i + 1];
    const p3 = values[Math.min(n - 1, i + 2)];
    for (let s = 0; s < perSegment; s += 1) {
      const t = s / perSegment;
      const t2 = t * t;
      const t3 = t2 * t;
      out.push(
        0.5 *
          (2 * p1 +
            (-p0 + p2) * t +
            (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
            (-p0 + 3 * p1 - 3 * p2 + p3) * t3),
      );
    }
  }
  out.push(values[n - 1]);
  return out;
}

function smoothPoints(values: number[], spanSecs: number): LivelinePoint[] {
  const dense = smooth(values);
  return makePoints(dense, spanSecs / (dense.length - 1));
}

function useDarkMode() {
  const [dark, setDark] = useState(true);

  useEffect(() => {
    const update = () =>
      setDark(!document.body.classList.contains("light"));
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return dark;
}

function Entity({ name, tone }: { name: string; tone: string }) {
  return (
    <span className={styles.entity}>
      <span
        className={styles.entityDot}
        style={{ background: tone }}
      />
      @{name}
    </span>
  );
}

function Mono({
  children,
  tone,
}: {
  children: ReactNode;
  tone: "red" | "green";
}) {
  return (
    <code className={`${styles.mono} ${tone === "red" ? styles.monoRed : styles.monoGreen}`}>
      {children}
    </code>
  );
}

function chartIndexFromPointer(
  event: ReactPointerEvent<HTMLDivElement>,
  pointCount: number,
) {
  const rect = event.currentTarget.getBoundingClientRect();
  const progress = Math.max(
    0,
    Math.min(1, (event.clientX - rect.left) / rect.width),
  );
  return Math.round(progress * (pointCount - 1));
}

function ChartTooltip({
  rows,
}: {
  rows: { label: string; value: string; color: string }[];
}) {
  return (
    <div className={styles.tooltip}>
      {rows.map((row) => (
        <span key={row.label} className={styles.tooltipItem}>
          <span
            className={styles.tooltipDot}
            style={{ background: row.color }}
          />
          {row.value}
        </span>
      ))}
    </div>
  );
}

export type CompareSeries = {
  name: string;
  values: number[];
  sub: string;
  tone: "red" | "green";
  dotColor: string;
  color: string;
  tooltipColor: string;
};

export type LiveAnalytics = {
  total_impressions: number;
  reach_change_pct: number;
  saves_change_pct: number;
  reach_series: number[];
  saves_series: number[];
  allocation: {
    name: string;
    label: string;
    pct: number;
    amount: string;
    color: string;
    textColor: string;
  }[];
  top_posts?: { caption: string; impressions: number; likes: number }[];
  is_live_data?: boolean;
};

function buildCompareSeries(analytics: LiveAnalytics | null): CompareSeries[] {
  if (analytics) {
    const reach = analytics.reach_series;
    const saves = analytics.saves_series;
    const reachLast = reach.at(-1) ?? analytics.reach_change_pct;
    const savesLast = saves.at(-1) ?? analytics.saves_change_pct;
    const impressionsTotal = analytics.total_impressions;
    return [
      {
        name: "Reach",
        values: reach,
        sub: `${reachLast >= 0 ? "+" : ""}${impressionsTotal.toLocaleString()} impressions`,
        tone: reachLast >= 0 ? "green" : "red",
        dotColor: reachLast >= 0 ? "#3d9aff" : "var(--orange)",
        color: reachLast >= 0 ? "#3d9aff" : "#f68f3c",
        tooltipColor: reachLast >= 0 ? "var(--blue)" : "var(--orange)",
      },
      {
        name: "Saves",
        values: saves,
        sub: `${savesLast >= 0 ? "+" : ""}${savesLast.toFixed(2)}%`,
        tone: savesLast >= 0 ? "green" : "red",
        dotColor: "#3d9aff",
        color: "#3d9aff",
        tooltipColor: "var(--blue)",
      },
    ];
  }
  // Baseline (no live data yet)
  return [
    {
      name: "Reach",
      values: [-2.9, -3.4, -3.05, -3.86, -3.52, -4.1, -3.82, -4.41],
      sub: "-2,377 impressions",
      tone: "red",
      dotColor: "var(--orange)",
      color: "#f68f3c",
      tooltipColor: "var(--orange)",
    },
    {
      name: "Saves",
      values: [0.22, 0.58, 0.42, 0.91, 0.76, 1.08, 0.96, 1.15],
      sub: "+617 saves",
      tone: "green",
      dotColor: "#3d9aff",
      color: "#3d9aff",
      tooltipColor: "var(--blue)",
    },
  ];
}

function CompareCard({ series = [] }: { series?: CompareSeries[] }) {
  const dark = useDarkMode();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const points = useMemo(
    () => series.map((s) => smoothPoints(s.values, 42)),
    [series],
  );
  const pointCount = points[0]?.length ?? 0;

  const chartSeries: LivelineSeries[] = useMemo(
    () =>
      series.map((s, i) => ({
        id: s.name,
        label: "",
        data: points[i],
        value: points[i].at(-1)?.value ?? (s.values.at(-1) ?? 0),
        color: s.color,
      })),
    [series, points],
  );

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        {series.map((s, i) => (
          <div key={s.name} className={styles.legendItem}>
            <span className={styles.legendLabel}>
              <span
                className={styles.legendDot}
                style={{ background: s.dotColor }}
              />
              {s.name}
            </span>
            <span
              className={`${styles.legendValue} ${
                s.tone === "red" ? styles.toneRed : styles.toneGreen
              }`}
            >
              {formatPercent(points[i].at(-1)?.value ?? (s.values.at(-1) ?? 0))}
            </span>
            <Mono tone={s.tone}>{s.sub}</Mono>
          </div>
        ))}
      </div>
      <div className={styles.chartBox}>
        <div className={styles.chartBoxHead}>
          <span className={styles.chartBoxLabel}>Trend snapshot</span>
          <span className={styles.chip}>Snapshot</span>
        </div>
        <div
          className={styles.chartStage}
          onPointerDown={(event) =>
            setHoverIndex(chartIndexFromPointer(event, pointCount))
          }
          onPointerMove={(event) =>
            setHoverIndex(chartIndexFromPointer(event, pointCount))
          }
          onPointerLeave={() => setHoverIndex(null)}
          onPointerCancel={() => setHoverIndex(null)}
          onPointerUp={() => setHoverIndex(null)}
        >
          <Liveline
            data={[]}
            value={0}
            series={chartSeries}
            theme={dark ? "dark" : "light"}
            grid={false}
            pulse={false}
            window={42}
            paused
            scrub={false}
            cursor="default"
            lineWidth={2.25}
            padding={{ top: 40, right: 0, bottom: 22, left: 0 }}
            formatValue={formatPercent}
          />
          {hoverIndex !== null && (
            <>
              <span
                className={styles.chartCursor}
                style={{
                  left: `${(hoverIndex / (pointCount - 1)) * 100}%`,
                }}
              />
              <span
                className={styles.tooltipAnchor}
                style={{
                  left: `${Math.min(
                    Math.max(
                      (hoverIndex / (pointCount - 1)) * 100,
                      28,
                    ),
                    72,
                  )}%`,
                }}
              >
                <ChartTooltip
                  rows={series.map((s, i) => ({
                    label: s.name,
                    value: formatPercent(points[i][hoverIndex].value),
                    color: s.tooltipColor,
                  }))}
                />
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export type AnomalyData = {
  spend: number[];
  usage: number[];
};

const ANOMALY_DATA: AnomalyData = {
  spend: [274, 289, 264, 307, 331, 1210, 1718, 2112],
  usage: [18, 19, 17, 21, 22, 58, 81, 96],
};

function AnomalyCard({ data: anomaly = ANOMALY_DATA }: { data?: AnomalyData }) {
  const dark = useDarkMode();
  const [metric, setMetric] = useState<"spend" | "usage">("spend");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const spend = useMemo(() => makePoints(anomaly.spend, 7), [anomaly]);
  const usage = useMemo(() => makePoints(anomaly.usage, 7), [anomaly]);

  const data = metric === "spend" ? spend : usage;
  const value = data.at(-1)?.value ?? (metric === "spend" ? 2112 : 96);
  const threshold = metric === "spend" ? "$2,112" : "82 kWh";
  const moneyLabel = formatMoney(spend.at(-1)?.value ?? 2112);

  return (
    <div className={styles.card}>
      <div className={styles.cardHeadRow}>
        <span className={styles.cardTitle}>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--red)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
          Unusual reach spike
        </span>
        <span className={styles.chip}>Snapshot</span>
      </div>
      <div className={styles.chartBox}>
        <div className={styles.chartBoxHead}>
          <span className={styles.chartBoxLabel}>
            {hoverIndex !== null
              ? metric === "spend"
                ? formatMoney(data[hoverIndex].value)
                : `${Math.round(data[hoverIndex].value)} views`
              : `${threshold} threshold`}
          </span>
          <span className={styles.segToggle}>
            {(["spend", "usage"] as const).map((item) => (
              <button
                key={item}
                type="button"
                aria-pressed={metric === item}
                onClick={() => setMetric(item)}
                className={`${styles.segBtn} ${
                  metric === item ? styles.segBtnActive : ""
                }`}
              >
                {item === "spend" ? "Spend" : "Usage"}
              </button>
            ))}
          </span>
        </div>
        <div
          className={`${styles.chartStage} ${styles.chartStageCrosshair}`}
          onPointerDown={(event) =>
            setHoverIndex(chartIndexFromPointer(event, data.length))
          }
          onPointerMove={(event) =>
            setHoverIndex(chartIndexFromPointer(event, data.length))
          }
          onPointerLeave={() => setHoverIndex(null)}
          onPointerCancel={() => setHoverIndex(null)}
          onPointerUp={() => setHoverIndex(null)}
        >
          <Liveline
            data={data}
            value={value}
            theme={dark ? "dark" : "light"}
            color="#ee5c61"
            grid
            scrub={false}
            fill={false}
            pulse={false}
            momentum={false}
            paused
            window={49}
            lineWidth={2.25}
            cursor="crosshair"
            padding={{ top: 34, right: 0, bottom: 22, left: 0 }}
            formatValue={(v) =>
              metric === "spend" ? formatMoney(v) : `${Math.round(v)} views`
            }
          />
          {hoverIndex !== null && (
            <>
              <span
                className={styles.chartCursor}
                style={{
                  left: `${(hoverIndex / (data.length - 1)) * 100}%`,
                }}
              />
              <span
                className={styles.tooltipAnchor}
                style={{
                  left: `${Math.min(
                    Math.max(
                      (hoverIndex / (data.length - 1)) * 100,
                      28,
                    ),
                    72,
                  )}%`,
                }}
              >
                <ChartTooltip
                  rows={[
                    {
                      label: metric === "spend" ? "Spend" : "Usage",
                      value:
                        metric === "spend"
                          ? formatMoney(data[hoverIndex].value)
                          : `${Math.round(data[hoverIndex].value)} views`,
                      color: "var(--red)",
                    },
                  ]}
                />
              </span>
            </>
          )}
        </div>
      </div>
      <div className={styles.footRow}>
        <span className={styles.footValue}>{moneyLabel} spent</span>
        <Mono tone="red">+$1,834.66</Mono>
        <span className={styles.footNote}>vs 3 months</span>
      </div>
    </div>
  );
}

export type AllocationSegment = {
  name: string;
  label: string;
  pct: number;
  amount: string;
  color: string;
  textColor: string;
};

const ALLOCATION_SEGMENTS: AllocationSegment[] = [
  {
    name: "VID",
    label: "Video",
    pct: 72.5,
    amount: "51,785 views",
    color: "#f68f3c",
    textColor: "var(--orange)",
  },
  {
    name: "IMG",
    label: "Images",
    pct: 22.8,
    amount: "16,278 views",
    color: "rgba(255,255,255,0.28)",
    textColor: "var(--text-dim)",
  },
  {
    name: "TXT",
    label: "Text",
    pct: 4.7,
    amount: "3,357 views",
    color: "rgba(255,255,255,0.12)",
    textColor: "var(--text-muted)",
  },
];

function AllocationCard({
  segments = ALLOCATION_SEGMENTS,
}: {
  segments?: AllocationSegment[];
}) {
  const [selected, setSelected] = useState(segments[0].name);
  const active =
    segments.find((segment) => segment.name === selected) ?? segments[0];

  return (
    <div className={styles.card}>
      <span className={styles.cardTitle}>
        <span
          className={styles.allocBadge}
          style={{ background: segments[0].color }}
        >
          {segments[0].name.charAt(0)}
        </span>
        {segments[0].label} allocation
      </span>
      <span className={styles.allocHero}>{active.amount}</span>
      <div
        className={styles.allocBar}
        role="group"
        aria-label="Allocation segments"
      >
        {segments.map((s) => (
          <button
            key={s.name}
            type="button"
            aria-pressed={selected === s.name}
            aria-label={`${s.label}: ${s.pct}%`}
            onClick={() => setSelected(s.name)}
            className={styles.allocSeg}
            style={{
              width: `${s.pct}%`,
              background: s.color,
              opacity: selected === s.name ? 1 : 0.58,
              boxShadow:
                selected === s.name
                  ? "inset 0 0 0 1px rgba(255,255,255,0.22)"
                  : undefined,
              transitionTimingFunction: EASE,
            }}
          >
            <span
              className={styles.allocFill}
              style={{
                width: selected === s.name ? "calc(100% - 8px)" : "0%",
                opacity: selected === s.name ? 1 : 0,
                transitionTimingFunction: EASE,
              }}
            />
          </button>
        ))}
      </div>
      <div className={styles.allocLegend}>
        {segments.map((s) => (
          <button
            key={s.name}
            type="button"
            aria-pressed={selected === s.name}
            onClick={() => setSelected(s.name)}
            className={`${styles.allocLegendBtn} ${
              selected === s.name ? styles.allocLegendBtnActive : ""
            }`}
          >
            <span
              className={styles.allocLegendDot}
              style={{ background: s.color }}
            />
            {s.name} <span className={styles.tabular}>{s.pct}%</span>
          </button>
        ))}
      </div>
      <div className={styles.noteBox}>
        <span className={styles.noteLabel} style={{ color: active.textColor }}>
          {active.label}
        </span>
        <span className={styles.noteText}>
          Contribution snapshot across current inventory value. Segment
          selection changes the inspected group without moving the card.
        </span>
      </div>
    </div>
  );
}

export type InsightPage = {
  key: string;
  prose: ReactNode;
  Card: ComponentType;
  pill: string;
};

export type InsightCardsLabels = {
  title: string;
};

const DEFAULT_INSIGHT_LABELS: InsightCardsLabels = {
  title: "Insights",
};

export default function InsightCards({
  pages,
  labels,
  onPill,
  analytics,
}: {
  pages?: InsightPage[];
  labels?: Partial<InsightCardsLabels>;
  onPill?: (text: string) => void;
  analytics?: LiveAnalytics | null;
} = {}) {
  const l = { ...DEFAULT_INSIGHT_LABELS, ...labels };
  const [page, setPage] = useState(0);

  // Build the compare series from live analytics (or static baseline)
  const compareSeries = buildCompareSeries(analytics ?? null);

  // Build dynamic allocation segments from live analytics if available
  const allocationSegments: AllocationSegment[] = analytics?.allocation
    ? analytics.allocation.map((a) => ({
        name: a.name,
        label: a.label,
        pct: a.pct,
        amount: a.amount,
        color: a.color,
        textColor: a.textColor,
      }))
    : ALLOCATION_SEGMENTS;

  // Build live prose for the compare page
  const reachSeries = compareSeries[0];
  const reachLast = reachSeries.values.at(-1) ?? 0;
  const compareProse = analytics ? (
    <>
      Your top channel is{" "}
      <Entity name={analytics.allocation[0]?.label ?? "Text"} tone={analytics.allocation[0]?.color ?? "var(--blue)"} />{" — "}
      <Mono tone="green">{analytics.allocation[0]?.pct.toFixed(1)}%</Mono> of total reach.
      Impressions:{" "}
      <Mono tone={reachLast >= 0 ? "green" : "red"}>
        {reachLast >= 0 ? "+" : ""}{analytics.total_impressions.toLocaleString()}
      </Mono>{" "}this period.
    </>
  ) : (
    <>
      The worst performer in your{" "}
      <Entity name="Feed" tone="var(--orange)" /> is single images — down{" "}
      <Mono tone="red">-4.41%</Mono> or <Mono tone="red">-2,377</Mono>{" "}
      impressions.
    </>
  );

  // Compose pages
  const resolvedPages: InsightPage[] = pages ?? [
    {
      key: "compare",
      prose: compareProse,
      Card: () => <CompareCard series={compareSeries} />,
      pill: "Should I rebalance my content mix?",
    },
    {
      key: "anomaly",
      prose: (
        <>
          Unusually high reach on{" "}
          <span className={styles.proseStrong}>Dec 13</span> —{" "}
          <Mono tone="red">+$1,834.66</Mono> above your average.
        </>
      ),
      Card: AnomalyCard,
      pill: "Get tips on cutting spend",
    },
    {
      key: "allocation",
      prose: analytics ? (
        <>
          Your top format is{" "}
          <Entity name={allocationSegments[0].label} tone={allocationSegments[0].color} /> — it's{" "}
          <span className={styles.proseStrong}>{allocationSegments[0].pct.toFixed(1)}%</span> of your views.
        </>
      ) : (
        <>
          You&apos;re heavily invested in{" "}
          <Entity name="Video" tone="var(--orange)" /> — it&apos;s{" "}
          <span className={styles.proseStrong}>72.5%</span> of your case.
        </>
      ),
      Card: () => <AllocationCard segments={allocationSegments} />,
      pill: "If we look at seasonals, what changes?",
    },
  ];

  const safePage = Math.min(page, resolvedPages.length - 1);
  const { prose, Card, pill } = resolvedPages[safePage];

  const move = (direction: -1 | 1) => {
    setPage((current) => (current + direction + resolvedPages.length) % resolvedPages.length);
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.pager}>
        <span className={styles.pagerTitleGroup}>
          <span className={styles.pagerTitle}>
            {l.title}
            {analytics?.is_live_data && (
              <span style={{ fontSize: "10px", marginLeft: "6px", color: "#3d9aff", fontWeight: 600 }}>
                LIVE
              </span>
            )}
          </span>
          <span className={styles.pagerCount}>{resolvedPages.length}</span>
        </span>
        <span className={styles.pagerBtns}>
          {(["M15 18l-6-6 6-6", "M9 6l6 6-6 6"] as const).map((d, i) => (
            <button
              key={i}
              type="button"
              aria-label={i === 0 ? "Previous insight" : "Next insight"}
              onClick={() => move(i === 0 ? -1 : 1)}
              className={styles.pagerBtn}
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d={d} />
              </svg>
            </button>
          ))}
        </span>
      </div>

      <div className={styles.content}>
        <p className={styles.prose}>{prose}</p>
        <div className={styles.cardSlot}>
          <Card />
        </div>
        <button
          type="button"
          className={styles.followPill}
          onClick={() => onPill?.(pill)}
        >
          {pill}
        </button>
      </div>
    </div>
  );
}
