"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  CreditCard,
  FileSearch,
  GitBranch,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  Webhook,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getLineageStatus,
  getOrder,
  getPayment,
  getReconciliationStatus,
  isAccessTokenProviderConfigured,
  listPayments,
  listWebhooks,
} from "../lib/api/client";
import { ApiError, apiErrorMessage } from "../lib/api/errors";
import { formatPaymentAmount } from "../lib/api/format";
import type { MerchantOrder, PaymentCapture, WebhookSummary } from "../lib/api/types";

type Page =
  | "overview"
  | "payments"
  | "reconciliation"
  | "investigations"
  | "lineage"
  | "webhooks"
  | "settings";

const PAGE_SIZE = 25;
const OVERVIEW_LIMIT = 100;
const isPayPalSandbox = process.env.NEXT_PUBLIC_PAYPAL_MODE?.trim().toLowerCase() === "sandbox";
const apiConfigured = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL?.trim());

const navItems: {
  id: Page;
  label: string;
  icon: typeof LayoutDashboard;
}[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "payments", label: "Payments", icon: CreditCard },
  { id: "reconciliation", label: "Reconciliation", icon: RefreshCcw },
  { id: "investigations", label: "Investigations", icon: FileSearch },
  { id: "lineage", label: "Transaction Lineage", icon: GitBranch },
  { id: "webhooks", label: "Webhooks", icon: Webhook },
  { id: "settings", label: "Settings", icon: Settings },
];

const pageCopy: Record<Page, { title: string; subtitle: string }> = {
  overview: {
    title: "Overview",
    subtitle: "A focused view of the payment records and webhook events returned by the API.",
  },
  payments: {
    title: "Payments",
    subtitle: "Review capture records returned by the connected PayPal payment API.",
  },
  reconciliation: {
    title: "Reconciliation",
    subtitle: "Review reconciliation service readiness and current read capabilities.",
  },
  investigations: {
    title: "Investigations",
    subtitle: "Investigation data is shown only when a real case or report can be retrieved.",
  },
  lineage: {
    title: "Transaction Lineage",
    subtitle: "Lineage availability is reported directly by the backend.",
  },
  webhooks: {
    title: "Webhooks",
    subtitle: "Review webhook delivery summaries returned by the backend.",
  },
  settings: {
    title: "Settings",
    subtitle: "Connection details available to this frontend session.",
  },
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not reported";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not reported";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function StatusTag({ value }: { value: string }) {
  const safeClass = value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return (
    <span className={"dp-status dp-status-" + safeClass}>
      <i aria-hidden="true" />
      {value}
    </span>
  );
}

function Panel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <section className={"dp-panel " + className}>{children}</section>;
}

function PanelHeading({
  title,
  note,
  action,
}: {
  title: string;
  note?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="dp-panel-heading">
      <div>
        <h2>{title}</h2>
        {note && <p>{note}</p>}
      </div>
      {action}
    </div>
  );
}

function LoadingState({ text }: { text: string }) {
  return (
    <div className="dp-state" role="status">
      <LoaderCircle className="dp-spin" size={18} />
      <span>{text}</span>
    </div>
  );
}

function ErrorState({
  error,
  title,
  retry,
}: {
  error: unknown;
  title: string;
  retry?: () => void;
}) {
  const status = error instanceof ApiError ? error.status : null;
  return (
    <div className="dp-state dp-state-error" role="alert">
      <AlertCircle size={19} aria-hidden="true" />
      <div>
        <strong>{title}{status ? " · HTTP " + status : ""}</strong>
        <p>{apiErrorMessage(error)}</p>
        {retry && (
          <button className="dp-button dp-button-secondary" onClick={retry}>
            Retry request
          </button>
        )}
      </div>
    </div>
  );
}

function EmptyState({
  title,
  text,
  icon: Icon = Activity,
}: {
  title: string;
  text: string;
  icon?: typeof Activity;
}) {
  return (
    <div className="dp-empty">
      <span className="dp-empty-icon"><Icon size={20} /></span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function RefreshButton({
  onClick,
  loading,
  label = "Refresh",
}: {
  onClick: () => void;
  loading: boolean;
  label?: string;
}) {
  return (
    <button className="dp-button dp-button-secondary" onClick={onClick} disabled={loading}>
      <RefreshCcw size={15} className={loading ? "dp-spin" : ""} />
      {label}
    </button>
  );
}

function DataTable({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  return (
    <div className="dp-table-scroll" role="region" aria-label={label} tabIndex={0}>
      <table className="dp-table">{children}</table>
    </div>
  );
}

function Overview({ navigate }: { navigate: (page: Page) => void }) {
  const [payments, setPayments] = useState<PaymentCapture[] | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookSummary[] | null>(null);
  const [reconciliation, setReconciliation] = useState<{ status: string; message: string } | null>(
    null,
  );
  const [paymentError, setPaymentError] = useState<unknown>(null);
  const [webhookError, setWebhookError] = useState<unknown>(null);
  const [reconciliationError, setReconciliationError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [lastCompleteRefresh, setLastCompleteRefresh] = useState<Date | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setPayments(null);
    setWebhooks(null);
    setReconciliation(null);
    setPaymentError(null);
    setWebhookError(null);
    setReconciliationError(null);
    setLastCompleteRefresh(null);

    void Promise.allSettled([
      listPayments(OVERVIEW_LIMIT, 0, controller.signal),
      listWebhooks(8, 0, controller.signal),
      getReconciliationStatus(controller.signal),
    ]).then(([paymentResult, webhookResult, reconciliationResult]) => {
      if (!active) return;
      if (paymentResult.status === "fulfilled") setPayments(paymentResult.value);
      else if (!isAbortError(paymentResult.reason)) setPaymentError(paymentResult.reason);
      if (webhookResult.status === "fulfilled") setWebhooks(webhookResult.value);
      else if (!isAbortError(webhookResult.reason)) setWebhookError(webhookResult.reason);
      if (reconciliationResult.status === "fulfilled") {
        setReconciliation(reconciliationResult.value);
      } else if (!isAbortError(reconciliationResult.reason)) {
        setReconciliationError(reconciliationResult.reason);
      }
      if (
        paymentResult.status === "fulfilled" &&
        webhookResult.status === "fulfilled" &&
        reconciliationResult.status === "fulfilled"
      ) {
        setLastCompleteRefresh(new Date());
      }
    }).finally(() => {
      if (active) setLoading(false);
    });

    return () => {
      active = false;
      controller.abort();
    };
  }, [refreshIndex]);

  const counts = useMemo(() => {
    const summary = { completed: 0, pending: 0, failed: 0, other: 0 };
    for (const payment of payments ?? []) {
      const status = payment.status.trim().toUpperCase();
      if (status === "COMPLETED") summary.completed += 1;
      else if (status === "PENDING") summary.pending += 1;
      else if (["FAILED", "DENIED", "DECLINED"].includes(status)) summary.failed += 1;
      else summary.other += 1;
    }
    return summary;
  }, [payments]);

  type ActivityPoint = { day: string; [status: string]: string | number };
  const activity = useMemo<ActivityPoint[]>(() => {
    const grouped = new Map<string, Map<string, number>>();
    for (const payment of payments ?? []) {
      const timestamp = payment.paypal_created_at ?? payment.paypal_updated_at;
      if (!timestamp) continue;
      const date = new Date(timestamp);
      if (Number.isNaN(date.getTime())) continue;
      const day = date.toISOString().slice(0, 10);
      const status = payment.status.trim().toUpperCase() || "UNKNOWN";
      const countsForDay = grouped.get(day) ?? new Map<string, number>();
      countsForDay.set(status, (countsForDay.get(status) ?? 0) + 1);
      grouped.set(day, countsForDay);
    }
    return Array.from(grouped, ([day, statuses]) => {
      const point: ActivityPoint = { day };
      statuses.forEach((count, status) => {
        point[status] = count;
      });
      return point;
    })
      .sort((left, right) => left.day.localeCompare(right.day));
  }, [payments]);
  const activityStatuses = useMemo(
    () => Array.from(new Set((payments ?? []).map((payment) => payment.status.trim().toUpperCase() || "UNKNOWN"))).sort(),
    [payments],
  );
  const activityColor = (status: string) => {
    if (status === "COMPLETED") return "#0070E0";
    if (status === "PENDING") return "#E5A100";
    if (["FAILED", "DENIED", "DECLINED"].includes(status)) return "#D64545";
    return "#6B7785";
  };

  const refresh = () => setRefreshIndex((index) => index + 1);
  const allDataAvailable =
    payments !== null && webhooks !== null && reconciliation !== null &&
    !paymentError && !webhookError && !reconciliationError;

  return (
    <div className="dp-stack">
      <div className="dp-refresh-row">
        <div className="dp-refresh-label">
          <span className={allDataAvailable ? "dp-live-dot" : "dp-neutral-dot"} />
          <span>
            {loading ? "Refreshing connected data" : allDataAvailable ? "All sources responded" : "Some data sources are unavailable"}
          </span>
          {lastCompleteRefresh && (
            <small>Last complete refresh {formatDate(lastCompleteRefresh.toISOString())}</small>
          )}
        </div>
        <RefreshButton onClick={refresh} loading={loading} label="Refresh data" />
      </div>

      {Boolean(paymentError || webhookError || reconciliationError) && (
        <div className="dp-inline-alert" role="status">
          {paymentError ? "Payment data unavailable. " : ""}
          {webhookError ? "Webhook data unavailable. " : ""}
          {reconciliationError ? "Reconciliation readiness unavailable." : ""}
          {payments !== null || webhooks !== null
            ? " Available sections below show only records returned by the API."
            : ""}
        </div>
      )}

      <section className="dp-overview-intro">
        <div>
          <span className="dp-eyebrow">PAYMENT OPERATIONS</span>
          <h2>Know what arrived.<br /><em>See what needs attention.</em></h2>
        </div>
        <p>
          A read-only snapshot of the latest records returned by your connected PayPal data API.
          Nothing here triggers reconciliation or changes a payment.
        </p>
      </section>

      <div className="dp-metric-strip">
        <Metric label="Captures loaded" value={payments === null ? "—" : String(payments.length)} note="Latest API page · up to 100" icon={CreditCard} />
        <Metric label="Completed" value={payments === null ? "—" : String(counts.completed)} note="Loaded capture records" icon={Check} />
        <Metric label="Pending" value={payments === null ? "—" : String(counts.pending)} note="Loaded capture records" icon={Clock3} />
        <Metric label="Failed" value={payments === null ? "—" : String(counts.failed)} note="Failed, denied, or declined" icon={AlertCircle} />
      </div>

      <div className="dp-overview-grid">
        <Panel className="dp-activity-panel">
          <PanelHeading
            title="Capture activity"
            note="Daily captures from this API page · UTC dates"
            action={<span className="dp-scope-tag">LOADED RECORDS</span>}
          />
          {paymentError ? (
            <ErrorState error={paymentError} title="Capture activity unavailable" retry={refresh} />
          ) : payments === null ? (
            loading ? <LoadingState text="Loading capture records…" /> :
              <EmptyState title="No capture data" text="The API did not return payment records." />
          ) : payments.length === 0 ? (
            <EmptyState title="No captures returned" text="There are no capture records on the current API page." />
          ) : activity.length === 0 ? (
            <EmptyState title="No dated captures" text="The returned records do not contain usable PayPal timestamps." />
          ) : activity.length < 2 ? (
            <EmptyState title="Not enough activity to chart" text="Fewer than two UTC dates are available. See the real capture rows below instead." />
          ) : (
            <>
              <div className="dp-activity-legend" aria-label="Capture statuses in this API page">
                {activityStatuses.map((status) => (
                  <span key={status}>
                    <i style={{ backgroundColor: activityColor(status) }} />
                    {status}
                  </span>
                ))}
              </div>
              <div className="dp-chart-wrap">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={activity} margin={{ top: 12, right: 12, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="captureFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#0070E0" stopOpacity={0.18} />
                        <stop offset="100%" stopColor="#0070E0" stopOpacity={0.01} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#E9EEF5" strokeDasharray="3 4" vertical={false} />
                    <XAxis
                      dataKey="day"
                      axisLine={false}
                      tickLine={false}
                      minTickGap={20}
                      tick={{ fill: "#687789", fontSize: 11 }}
                      tickFormatter={(day: string) => day.slice(5)}
                    />
                    <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: "#687789", fontSize: 11 }} />
                    <Tooltip
                      labelFormatter={(day) => "UTC " + String(day)}
                      formatter={(value, name) => [value, String(name)]}
                      contentStyle={{ border: "1px solid #E2E8F0", borderRadius: 8, color: "#001435" }}
                    />
                    {activityStatuses.map((status) => (
                      <Area
                        key={status}
                        type="monotone"
                        dataKey={status}
                        name={status}
                        stroke={activityColor(status)}
                        strokeWidth={2}
                        fill="transparent"
                        connectNulls
                        activeDot={{ r: 4 }}
                      />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <div className="dp-chart-foot">
                <span>{activity.reduce((total, day) => total + activityStatuses.reduce((daily, status) => daily + Number(day[status] ?? 0), 0), 0)} dated captures</span>
                <span>{payments.length} records loaded · no database-wide total</span>
              </div>
            </>
          )}
        </Panel>

        <Panel className="dp-readiness-panel">
          <PanelHeading title="Reconciliation" note="Service readiness only" />
          {reconciliationError ? (
            <ErrorState error={reconciliationError} title="Readiness unavailable" retry={refresh} />
          ) : reconciliation === null ? (
            loading ? <LoadingState text="Checking service readiness…" /> :
              <EmptyState title="Readiness unavailable" text="The service did not return a readiness status." icon={ShieldCheck} />
          ) : (
            <div className="dp-readiness-result">
              <span className={reconciliation.status.toLowerCase() === "ready" ? "dp-readiness-mark ready" : "dp-readiness-mark"}>
                {reconciliation.status.toLowerCase() === "ready" ? <Check size={19} /> : <AlertCircle size={19} />}
              </span>
              <div>
                <strong>{reconciliation.status}</strong>
                <p>{reconciliation.message}</p>
              </div>
            </div>
          )}
          <div className="dp-divider" />
          <p className="dp-muted-copy">
            Persisted exception cases are not available through a list endpoint. No reconciliation run is started from this screen.
          </p>
          <button className="dp-text-button" onClick={() => navigate("reconciliation")}>
            Read reconciliation availability <ChevronRight size={15} />
          </button>
        </Panel>
      </div>

      <div className="dp-lower-grid">
        <Panel>
          <PanelHeading
            title="Recent captures"
            note={payments === null ? "Current API page" : "First records from the latest API page"}
            action={<button className="dp-text-button" onClick={() => navigate("payments")}>View payments <ChevronRight size={15} /></button>}
          />
          {paymentError ? <ErrorState error={paymentError} title="Captures unavailable" retry={refresh} /> :
            payments === null ? (loading ? <LoadingState text="Loading captures…" /> : null) :
              <CaptureTable payments={payments.slice(0, 5)} />}
        </Panel>
        <Panel>
          <PanelHeading
            title="Recent webhooks"
            note={webhooks === null ? "Latest summaries from the API" : webhooks.length + " summaries loaded"}
            action={<button className="dp-text-button" onClick={() => navigate("webhooks")}>View webhooks <ChevronRight size={15} /></button>}
          />
          {webhookError ? <ErrorState error={webhookError} title="Webhook summaries unavailable" retry={refresh} /> :
            webhooks === null ? (loading ? <LoadingState text="Loading webhook summaries…" /> : null) :
              <WebhookPreview events={webhooks.slice(0, 5)} />}
        </Panel>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  note,
  icon: Icon,
}: {
  label: string;
  value: string;
  note: string;
  icon: typeof Activity;
}) {
  return (
    <div className="dp-metric">
      <div className="dp-metric-icon"><Icon size={17} /></div>
      <div className="dp-metric-body">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{note}</small>
      </div>
    </div>
  );
}

function CaptureTable({ payments }: { payments: PaymentCapture[] }) {
  if (payments.length === 0) {
    return <EmptyState title="No captures returned" text="No records are available on this API page." icon={CreditCard} />;
  }
  return (
    <DataTable label="Recent payment captures">
      <thead>
        <tr><th>Capture</th><th>PayPal order</th><th>Amount</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {payments.map((payment) => (
          <tr key={payment.payment_id}>
            <td className="dp-mono">{payment.payment_id}</td>
            <td className="dp-mono">{payment.order_id}</td>
            <td className="dp-amount">{formatPaymentAmount(payment.amount, payment.currency)}</td>
            <td><StatusTag value={payment.status} /></td>
            <td>{formatDate(payment.paypal_created_at ?? payment.paypal_updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

function WebhookPreview({ events }: { events: WebhookSummary[] }) {
  if (events.length === 0) {
    return <EmptyState title="No webhook events returned" text="The API returned an empty page of webhook summaries." icon={Webhook} />;
  }
  return (
    <div className="dp-webhook-preview">
      {events.map((event) => (
        <div className="dp-webhook-preview-row" key={event.event_id}>
          <span className="dp-webhook-icon"><Webhook size={15} /></span>
          <div className="dp-webhook-preview-content">
            <strong>{event.event_type}</strong>
            <small>{event.event_id} · {formatDate(event.received_at)}</small>
          </div>
          <StatusTag value={event.processing_status} />
        </div>
      ))}
    </div>
  );
}

function loadPageOrders(
  payments: PaymentCapture[],
  signal: AbortSignal,
): Promise<Map<string, MerchantOrder>> {
  const orderIds = Array.from(new Set(payments.map((payment) => payment.order_id)));
  const orders = new Map<string, MerchantOrder>();
  return (async () => {
    for (let start = 0; start < orderIds.length; start += 5) {
      const batch = orderIds.slice(start, start + 5);
      const results = await Promise.all(batch.map(async (orderId) => {
        try {
          return await getOrder(orderId, signal);
        } catch (error) {
          if (error instanceof ApiError && error.isNotFound) return null;
          throw error;
        }
      }));
      results.forEach((order) => {
        if (order) orders.set(order.order_id, order);
      });
    }
    return orders;
  })();
}

function Payments({
  onRefreshed,
}: {
  onRefreshed: (at: Date) => void;
}) {
  const [payments, setPayments] = useState<PaymentCapture[]>([]);
  const [orders, setOrders] = useState<Map<string, MerchantOrder>>(() => new Map());
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("All statuses");
  const [offset, setOffset] = useState(0);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selectedPaymentId, setSelectedPaymentId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    setPayments([]);
    setOrders(new Map());
    void (async () => {
      try {
        const page = await listPayments(PAGE_SIZE, offset, controller.signal);
        const relatedOrders = await loadPageOrders(page, controller.signal);
        if (active) {
          setPayments(page);
          setOrders(relatedOrders);
          onRefreshed(new Date());
        }
      } catch (caught) {
        if (active && !isAbortError(caught)) setError(caught);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset, refreshIndex, onRefreshed]);

  const statuses = useMemo(
    () => Array.from(new Set(payments.map((item) => item.status))),
    [payments],
  );
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return payments.filter((payment) => {
      const order = orders.get(payment.order_id);
      const matchesStatus = status === "All statuses" || payment.status === status;
      const matchesQuery = !normalized ||
        [payment.payment_id, payment.order_id, order?.merchant_reference ?? "", order?.invoice_id ?? ""]
          .some((value) => value.toLowerCase().includes(normalized));
      return matchesStatus && matchesQuery;
    });
  }, [orders, payments, query, status]);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const refresh = () => setRefreshIndex((value) => value + 1);

  return (
    <>
      <div className="dp-page-toolbar">
        <label className="dp-search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search the loaded payment page"
            placeholder="Search capture, order, or merchant reference"
          />
          {query && <button aria-label="Clear search" onClick={() => setQuery("")}><X size={14} /></button>}
        </label>
        <select aria-label="Filter payment status on this page" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option>All statuses</option>
          {statuses.map((value) => <option key={value}>{value}</option>)}
        </select>
        <RefreshButton onClick={refresh} loading={loading} label="Refresh" />
      </div>

      <Panel className="dp-data-panel">
        <PanelHeading
          title="Payment captures"
          note={error ? "Record count unavailable" : filtered.length + " shown · " + payments.length + " loaded on this API page"}
        />
        {loading && payments.length === 0 ? (
          <LoadingState text="Loading payment captures…" />
        ) : error ? (
          <ErrorState error={error} title="Payment data unavailable" retry={refresh} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={payments.length === 0 ? "No payment records returned" : "No matching captures"}
            text={payments.length === 0
              ? offset === 0 ? "The API returned an empty page for this merchant." : "There are no further records on the next API page."
              : "No records on this API page match the current search and status filter."}
            icon={CreditCard}
          />
        ) : (
          <DataTable label="Payment captures returned by the API">
            <thead>
              <tr><th>Capture ID</th><th>PayPal order</th><th>Merchant reference</th><th>Amount</th><th>Status</th><th>Created</th><th>Updated</th><th /></tr>
            </thead>
            <tbody>
              {filtered.map((payment) => {
                const order = orders.get(payment.order_id);
                return (
                  <tr
                    key={payment.payment_id}
                    className="dp-click-row"
                    onClick={() => setSelectedPaymentId(payment.payment_id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedPaymentId(payment.payment_id);
                      }
                    }}
                    tabIndex={0}
                    aria-label={"Open capture " + payment.payment_id}
                  >
                    <td><button className="dp-link-button" onClick={(event) => { event.stopPropagation(); setSelectedPaymentId(payment.payment_id); }}>{payment.payment_id}</button></td>
                    <td className="dp-mono">{payment.order_id}</td>
                    <td>{order?.merchant_reference ?? order?.invoice_id ?? "Not reported"}</td>
                    <td className="dp-amount">{formatPaymentAmount(payment.amount, payment.currency)}</td>
                    <td><StatusTag value={payment.status} /></td>
                    <td>{formatDate(payment.paypal_created_at)}</td>
                    <td>{formatDate(payment.paypal_updated_at)}</td>
                    <td><ChevronRight size={15} /></td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        )}
        <div className="dp-pagination">
          <span>Page {currentPage} · the API does not return a total</span>
          <div>
            <button aria-label="Previous payments page" disabled={loading || offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}><ChevronLeft size={16} /></button>
            <button aria-label="Next payments page" disabled={loading || payments.length < PAGE_SIZE} onClick={() => setOffset((value) => value + PAGE_SIZE)}><ChevronRight size={16} /></button>
          </div>
        </div>
      </Panel>
      {selectedPaymentId && (
        <PaymentDetails paymentId={selectedPaymentId} onClose={() => setSelectedPaymentId(null)} />
      )}
    </>
  );
}

function PaymentDetails({ paymentId, onClose }: { paymentId: string; onClose: () => void }) {
  const [payment, setPayment] = useState<PaymentCapture | null>(null);
  const [order, setOrder] = useState<MerchantOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [orderError, setOrderError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setPayment(null);
    setOrder(null);
    setError(null);
    setOrderError(null);
    setLoading(true);
    void (async () => {
      try {
        const capture = await getPayment(paymentId, controller.signal);
        if (active) setPayment(capture);
        try {
          const relatedOrder = await getOrder(capture.order_id, controller.signal);
          if (active) setOrder(relatedOrder);
        } catch (caught) {
          if (active && !(caught instanceof ApiError && caught.isNotFound) && !isAbortError(caught)) {
            setOrderError(caught);
          }
        }
      } catch (caught) {
        if (active && !isAbortError(caught)) setError(caught);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [paymentId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="dp-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="dp-drawer" role="dialog" aria-modal="true" aria-label="Payment capture details">
        <div className="dp-drawer-head">
          <div>
            <span className="dp-eyebrow">CAPTURE DETAILS</span>
            <h2 className="dp-break">{paymentId}</h2>
          </div>
          <button className="dp-icon-button" onClick={onClose} aria-label="Close payment details"><X size={18} /></button>
        </div>
        <div className="dp-drawer-body">
          {loading ? <LoadingState text="Loading the capture and related order…" /> :
            error ? <ErrorState error={error} title="Capture details unavailable" /> :
              payment ? (
                <>
                  <div className="dp-detail-amount">
                    <span>Captured amount</span>
                    <strong>{formatPaymentAmount(payment.amount, payment.currency)}</strong>
                    <small>Refunded amount · {formatPaymentAmount(payment.refunded_amount, payment.currency)}</small>
                    <StatusTag value={payment.status} />
                  </div>
                  <DetailBlock title="Capture">
                    <DetailRow label="Capture ID" value={payment.payment_id} />
                    <DetailRow label="PayPal order ID" value={payment.order_id} />
                    <DetailRow label="Currency" value={payment.currency ?? "Not reported"} />
                    <DetailRow label="Created" value={formatDate(payment.paypal_created_at)} />
                    <DetailRow label="Updated" value={formatDate(payment.paypal_updated_at)} />
                  </DetailBlock>
                  <DetailBlock title="Related merchant order">
                    {order ? (
                      <>
                        <DetailRow label="Order ID" value={order.order_id} />
                        <DetailRow label="Merchant reference" value={order.merchant_reference ?? "Not reported"} />
                        <DetailRow label="Invoice ID" value={order.invoice_id ?? "Not reported"} />
                        <DetailRow label="Amount" value={formatPaymentAmount(order.amount, order.currency)} />
                        <DetailRow label="Intent" value={order.intent ?? "Not reported"} />
                        <DetailRow label="Order status" value={order.status ?? "Not reported"} />
                        <DetailRow label="Created" value={formatDate(order.created_at)} />
                        <DetailRow label="Updated" value={formatDate(order.updated_at)} />
                      </>
                    ) : orderError ? (
                      <p className="dp-inline-error">{apiErrorMessage(orderError)}</p>
                    ) : (
                      <p className="dp-muted-copy">No related merchant order record was found for this capture.</p>
                    )}
                  </DetailBlock>
                </>
              ) : null}
        </div>
      </aside>
    </div>
  );
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="dp-detail-block"><h3>{title}</h3>{children}</section>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return <div className="dp-detail-row"><span>{label}</span><strong className="dp-break">{value}</strong></div>;
}

function ReconciliationPage() {
  const [result, setResult] = useState<{ status: string; message: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshIndex, setRefreshIndex] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    setResult(null);
    void getReconciliationStatus(controller.signal).then((value) => {
      if (active) setResult(value);
    }).catch((caught) => {
      if (active && !isAbortError(caught)) setError(caught);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; controller.abort(); };
  }, [refreshIndex]);
  const retry = () => setRefreshIndex((value) => value + 1);
  return (
    <div className="dp-stack">
      <Panel>
        <PanelHeading title="Service readiness" note="Read-only response from GET /api/reconciliation" action={<RefreshButton onClick={retry} loading={loading} />} />
        {loading ? <LoadingState text="Checking reconciliation readiness…" /> :
          error ? <ErrorState error={error} title="Reconciliation status unavailable" retry={retry} /> :
            result ? (
              <div className="dp-readiness-result dp-readiness-large">
                <span className={result.status.toLowerCase() === "ready" ? "dp-readiness-mark ready" : "dp-readiness-mark"}>
                  {result.status.toLowerCase() === "ready" ? <Check size={20} /> : <AlertCircle size={20} />}
                </span>
                <div>
                  <span className="dp-eyebrow">API STATUS</span>
                  <strong>{result.status}</strong>
                  <p>{result.message}</p>
                </div>
              </div>
            ) : null}
      </Panel>
      <Panel>
        <PanelHeading title="Persisted reconciliation results" note="Exception case details are not available for listing in the current API contract." />
        <EmptyState
          title="Exception list unavailable"
          text="The backend provides readiness and a reconciliation run action, but no read endpoint for persisted exception cases. This screen will not start a run or imply that cases were reviewed."
          icon={ShieldCheck}
        />
      </Panel>
    </div>
  );
}

function InvestigationsPage() {
  return (
    <Panel>
      <PanelHeading title="Investigation reports" note="Reports and cases are addressable by known IDs only." />
      <EmptyState
        title="No case or report list is available"
        text="The current API can retrieve an investigation for a known case or report ID, but it does not expose a global list. No sample case, report, evidence, or AI conclusion is shown here."
        icon={FileSearch}
      />
    </Panel>
  );
}

function LineagePage() {
  const [status, setStatus] = useState<{ status: string; message: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshIndex, setRefreshIndex] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setStatus(null);
    setError(null);
    void getLineageStatus(controller.signal).then((value) => {
      if (active) setStatus(value);
    }).catch((caught) => {
      if (active && !isAbortError(caught)) setError(caught);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; controller.abort(); };
  }, [refreshIndex]);
  const retry = () => setRefreshIndex((value) => value + 1);
  return (
    <Panel>
      <PanelHeading title="Lineage API status" note="Read-only response from GET /api/lineage" action={<RefreshButton onClick={retry} loading={loading} />} />
      {loading ? <LoadingState text="Checking lineage availability…" /> :
        error ? <ErrorState error={error} title="Lineage status unavailable" retry={retry} /> :
          status ? (
            <div className="dp-api-status">
              <StatusTag value={status.status} />
              <p>{status.message}</p>
              {status.status.toLowerCase() === "placeholder" && (
                <EmptyState title="Lineage graph is not available yet" text="The backend currently returns a placeholder status. No relationships or evidence graph are inferred by the frontend." icon={GitBranch} />
              )}
            </div>
          ) : null}
    </Panel>
  );
}

function WebhooksPage() {
  const [events, setEvents] = useState<WebhookSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    setEvents([]);
    void listWebhooks(PAGE_SIZE, offset, controller.signal).then((value) => {
      if (active) setEvents(value);
    }).catch((caught) => {
      if (active && !isAbortError(caught)) setError(caught);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; controller.abort(); };
  }, [offset, refreshIndex]);
  const retry = () => setRefreshIndex((value) => value + 1);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  return (
    <Panel className="dp-data-panel">
      <PanelHeading
        title="Webhook deliveries"
        note={error ? "Event count unavailable" : events.length + " summaries returned on this API page"}
        action={<RefreshButton onClick={retry} loading={loading} />}
      />
      {loading && events.length === 0 ? <LoadingState text="Loading webhook summaries…" /> :
        error ? <ErrorState error={error} title="Webhook summaries unavailable" retry={retry} /> :
          events.length === 0 ? <EmptyState title="No webhook events returned" text="The API returned an empty page of webhook summaries." icon={Webhook} /> : (
            <DataTable label="Webhook event summaries">
              <thead>
                <tr><th>Event ID</th><th>Event type</th><th>Resource</th><th>Occurred</th><th>Received</th><th>Verification</th><th>Processing</th></tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.event_id}>
                    <td className="dp-mono">{event.event_id}</td>
                    <td>{event.event_type}</td>
                    <td>{event.resource_type ?? "Not reported"}{event.resource_id ? <small className="dp-subcell dp-mono">{event.resource_id}</small> : null}</td>
                    <td>{formatDate(event.occurred_at)}</td>
                    <td>{formatDate(event.received_at)}</td>
                    <td><StatusTag value={event.verification_status} /></td>
                    <td>
                      <StatusTag value={event.processing_status} />
                      {event.processing_error && <small className="dp-subcell">{event.processing_error}</small>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
      <div className="dp-pagination">
        <span>Page {currentPage} · the API does not return a total</span>
        <div>
          <button aria-label="Previous webhook page" disabled={loading || offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}><ChevronLeft size={16} /></button>
          <button aria-label="Next webhook page" disabled={loading || events.length < PAGE_SIZE} onClick={() => setOffset((value) => value + PAGE_SIZE)}><ChevronRight size={16} /></button>
        </div>
      </div>
    </Panel>
  );
}

function SettingsPage() {
  const tokenProviderConnected = isAccessTokenProviderConfigured();
  return (
    <div className="dp-settings-grid">
      <Panel>
        <PanelHeading title="API connection" note="Frontend configuration only" />
        <div className="dp-setting-row">
          <span>API base URL configured</span>
          <StatusTag value={apiConfigured ? "Configured" : "Missing"} />
        </div>
        <div className="dp-setting-row">
          <span>Access token provider</span>
          <StatusTag value={tokenProviderConnected ? "Connected" : "Not connected"} />
        </div>
        <div className="dp-setting-row">
          <span>PayPal mode</span>
          <strong>{isPayPalSandbox ? "PayPal Sandbox" : "Not identified as Sandbox"}</strong>
        </div>
        <p className="dp-muted-copy">
          The frontend does not create or store access tokens. A trusted identity provider must supply short-lived tokens before protected live data can load.
        </p>
      </Panel>
      <Panel>
        <PanelHeading title="Profile and workspace" note="No identity or profile API is connected." />
        <EmptyState title="Profile details unavailable" text="No user, merchant workspace, or account profile is inferred or displayed without a trusted identity response." icon={Settings} />
      </Panel>
    </div>
  );
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export default function DashboardApp() {
  const [page, setPage] = useState<Page>("overview");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paymentsRefreshAt, setPaymentsRefreshAt] = useState<Date | null>(null);
  const navigate = useCallback((next: Page) => {
    setPage(next);
    setMobileOpen(false);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);
  const recordPaymentRefresh = useCallback((at: Date) => setPaymentsRefreshAt(at), []);
  const copy = pageCopy[page];

  return (
    <div className="dp-shell">
      {mobileOpen && <button className="dp-mobile-backdrop" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />}
      <aside className={"dp-sidebar" + (mobileOpen ? " dp-sidebar-open" : "")}>
        <div className="dp-brand-row">
          <span className="dp-brand-mark" aria-hidden="true"><i /></span>
          <span className="dp-brand-name">DapPay</span>
          <button className="dp-icon-button dp-mobile-close" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X size={18} /></button>
        </div>
        <div className="dp-side-label">WORKSPACE</div>
        {isPayPalSandbox ? (
          <div className="dp-environment"><span />PayPal Sandbox</div>
        ) : (
          <div className="dp-environment dp-environment-muted">Environment not identified</div>
        )}
        <nav className="dp-nav" aria-label="Main navigation">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={"dp-nav-item" + (page === id ? " active" : "")} onClick={() => navigate(id)} aria-current={page === id ? "page" : undefined}>
              <Icon size={18} strokeWidth={page === id ? 2.1 : 1.8} />
              <span>{label}</span>
              {id === "webhooks" && <span className="dp-nav-note">API</span>}
            </button>
          ))}
        </nav>
        <div className="dp-sidebar-bottom">
          <span className="dp-sidebar-caption">READ-ONLY OPERATIONS</span>
          <p>Live data appears only when the backend and identity provider are connected.</p>
        </div>
      </aside>

      <div className="dp-main">
        <header className="dp-topbar">
          <button className="dp-icon-button dp-menu-button" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={19} /></button>
          <div className="dp-topbar-context">
            <span>DapPay</span><ChevronRight size={13} /><strong>{copy.title}</strong>
          </div>
          <div className="dp-topbar-right">
            {isPayPalSandbox && <span className="dp-mode-pill"><i />PayPal Sandbox</span>}
            {page === "payments" && paymentsRefreshAt && (
              <span className="dp-topbar-refresh">Updated {formatDate(paymentsRefreshAt.toISOString())}</span>
            )}
          </div>
        </header>
        <main className="dp-content">
          <div className="dp-page-heading">
            <div>
              <span className="dp-eyebrow">DAPPAY OPERATIONS</span>
              <h1>{copy.title}</h1>
              <p>{copy.subtitle}</p>
            </div>
          </div>
          {page === "overview" && <Overview navigate={navigate} />}
          {page === "payments" && <Payments onRefreshed={recordPaymentRefresh} />}
          {page === "reconciliation" && <ReconciliationPage />}
          {page === "investigations" && <InvestigationsPage />}
          {page === "lineage" && <LineagePage />}
          {page === "webhooks" && <WebhooksPage />}
          {page === "settings" && <SettingsPage />}
          <footer className="dp-footer">DapPay · independent payment operations workspace</footer>
        </main>
      </div>
    </div>
  );
}
