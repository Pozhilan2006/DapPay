"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Bell,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  CreditCard,
  FileSearch,
  Filter,
  GitBranch,
  HelpCircle,
  LayoutDashboard,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  WalletCards,
  X,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Background,
  Controls,
  Edge,
  MarkerType,
  MiniMap,
  Node,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  activityData,
  formatDate,
  formatMoney,
  investigations,
  Investigation,
  reconciliationData,
  transactions,
  Transaction,
} from "./data";

type Page = "overview" | "payments" | "reconciliation" | "investigations" | "lineage" | "settings";

const navItems = [
  { id: "overview" as Page, label: "Overview", icon: LayoutDashboard },
  { id: "payments" as Page, label: "Payments", icon: CreditCard },
  { id: "reconciliation" as Page, label: "Reconciliation", icon: RefreshCcw },
  { id: "investigations" as Page, label: "Investigations", icon: FileSearch, count: 4 },
  { id: "lineage" as Page, label: "Transaction Lineage", icon: GitBranch },
  { id: "settings" as Page, label: "Settings", icon: Settings },
];

const titles: Record<Page, { title: string; subtitle: string }> = {
  overview: {
    title: "Financial overview",
    subtitle: "Monitor payment performance and reconciliation health.",
  },
  payments: { title: "Payments", subtitle: "Search, review, and track every payment transaction." },
  reconciliation: {
    title: "Reconciliation",
    subtitle: "Compare PayPal settlements against merchant records.",
  },
  investigations: {
    title: "AI investigations",
    subtitle: "Review discrepancies prioritized by intelligent analysis.",
  },
  lineage: {
    title: "Transaction lineage",
    subtitle: "Trace a payment across every system and event.",
  },
  settings: { title: "Settings", subtitle: "Manage your workspace preferences and notifications." },
};

function StatusBadge({ value }: { value: string }) {
  const key = value.toLowerCase().replace(" ", "-");
  return (
    <span className={`badge badge-${key}`}>
      <span className="badge-dot" />
      {value}
    </span>
  );
}

function StatCard({
  label,
  value,
  change,
  icon: Icon,
  tone = "blue",
}: {
  label: string;
  value: string;
  change?: string;
  icon: typeof Activity;
  tone?: string;
}) {
  return (
    <div className="stat-card">
      <div className={`stat-icon tone-${tone}`}>
        <Icon size={19} />
      </div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {change && (
        <div className="stat-change">
          <span>↗ {change}</span> vs. last month
        </div>
      )}
    </div>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}

function CardHeader({
  title,
  caption,
  action,
}: {
  title: string;
  caption?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="card-header">
      <div>
        <h2>{title}</h2>
        {caption && <p>{caption}</p>}
      </div>
      {action}
    </div>
  );
}

function Overview({
  navigate,
  openTransaction,
  openInvestigation,
}: {
  navigate: (page: Page) => void;
  openTransaction: (item: Transaction) => void;
  openInvestigation: (item: Investigation) => void;
}) {
  return (
    <>
      <div className="stats-grid stats-grid-four">
        <StatCard label="Total transactions" value="12,482" change="8.4%" icon={WalletCards} />
        <StatCard
          label="Successful payments"
          value="11,946"
          change="6.2%"
          icon={Check}
          tone="green"
        />
        <StatCard label="Pending payments" value="184" icon={Clock3} tone="amber" />
        <StatCard label="Failed payments" value="352" icon={AlertCircle} tone="red" />
      </div>
      <div className="stats-grid stats-grid-four compact-stats">
        <StatCard label="Match rate" value="94.7%" change="2.1%" icon={ShieldCheck} tone="navy" />
        <StatCard label="Unmatched" value="142" icon={RefreshCcw} tone="amber" />
        <StatCard label="Active investigations" value="24" icon={FileSearch} tone="purple" />
        <StatCard label="Discrepancy amount" value="$18,429" icon={CircleDollarSign} tone="red" />
      </div>
      <div className="dashboard-grid">
        <Card className="chart-card">
          <CardHeader
            title="Payment activity"
            caption="Successful, failed, and pending payments"
            action={
              <button className="select-button">
                Last 7 days <ChevronDown size={14} />
              </button>
            }
          />
          <div className="chart-legend">
            <span>
              <i className="legend-success" />
              Successful
            </span>
            <span>
              <i className="legend-failed" />
              Failed
            </span>
            <span>
              <i className="legend-pending" />
              Pending
            </span>
          </div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={activityData} margin={{ left: -20, right: 8 }}>
                <defs>
                  <linearGradient id="successFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#60A5FA" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#60A5FA" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E8EDF3" />
                <XAxis
                  dataKey="day"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "#778392", fontSize: 11 }}
                />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "#778392", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    border: "1px solid #E2E8F0",
                    borderRadius: 10,
                    boxShadow: "0 8px 25px rgba(11,42,74,.1)",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="successful"
                  stroke="#0B2A4A"
                  strokeWidth={2.5}
                  fill="url(#successFill)"
                />
                <Area
                  type="monotone"
                  dataKey="failed"
                  stroke="#EF4444"
                  strokeWidth={2}
                  fill="transparent"
                />
                <Area
                  type="monotone"
                  dataKey="pending"
                  stroke="#F59E0B"
                  strokeWidth={2}
                  fill="transparent"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card className="donut-card">
          <CardHeader title="Reconciliation health" caption="Current matching performance" />
          <div className="donut-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={reconciliationData}
                  innerRadius={62}
                  outerRadius={82}
                  paddingAngle={3}
                  dataKey="value"
                  stroke="none"
                >
                  {reconciliationData.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="donut-center">
              <strong>94.7%</strong>
              <span>matched</span>
            </div>
          </div>
          <div className="health-row">
            <span>
              <i className="navy-dot" />
              Matched records
            </span>
            <strong>11,824</strong>
          </div>
          <div className="health-row">
            <span>
              <i className="blue-dot" />
              Needs review
            </span>
            <strong>658</strong>
          </div>
          <button className="text-button full" onClick={() => navigate("reconciliation")}>
            View reconciliation <ChevronRight size={15} />
          </button>
        </Card>
      </div>
      <div className="dashboard-grid bottom-grid">
        <Card className="table-card">
          <CardHeader
            title="Recent transactions"
            caption="Latest payment activity"
            action={
              <button className="text-button" onClick={() => navigate("payments")}>
                View all <ChevronRight size={15} />
              </button>
            }
          />
          <TransactionTable rows={transactions.slice(0, 5)} onOpen={openTransaction} compact />
        </Card>
        <Card className="alerts-card">
          <CardHeader
            title="Investigation alerts"
            caption="AI-prioritized issues"
            action={
              <button className="icon-button">
                <SlidersHorizontal size={16} />
              </button>
            }
          />
          <div className="alert-list">
            {investigations.slice(0, 4).map((item) => (
              <button className="alert-item" key={item.id} onClick={() => openInvestigation(item)}>
                <div className={`severity-icon severity-${item.severity.toLowerCase()}`}>
                  <AlertCircle size={16} />
                </div>
                <div>
                  <div className="alert-title">
                    {item.category}
                    <span>{item.id}</span>
                  </div>
                  <p>{item.summary}</p>
                  <small>{item.transactionId} · 18 min ago</small>
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}

function TransactionTable({
  rows,
  onOpen,
  compact = false,
}: {
  rows: Transaction[];
  onOpen: (item: Transaction) => void;
  compact?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Transaction</th>
            <th>Customer</th>
            {!compact && <th>PayPal reference</th>}
            <th>Amount</th>
            <th>Status</th>
            <th>Date</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.id} onClick={() => onOpen(item)}>
              <td>
                <button className="id-link">{item.id}</button>
                <small>{item.orderId}</small>
              </td>
              <td>{item.customer}</td>
              {!compact && <td className="mono">{item.paypalRef}</td>}
              <td className="amount">{formatMoney(item.amount)}</td>
              <td>
                <StatusBadge value={item.status} />
              </td>
              <td>{formatDate(item.date, true)}</td>
              <td>
                <ChevronRight size={15} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Payments({ openTransaction }: { openTransaction: (item: Transaction) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("All");
  const [sortDesc, setSortDesc] = useState(true);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const perPage = 6;
  const filtered = useMemo(
    () =>
      transactions
        .filter(
          (item) =>
            (status === "All" || item.status === status) &&
            [item.id, item.paypalRef, item.orderId, item.customer].some((value) =>
              value.toLowerCase().includes(query.toLowerCase()),
            ),
        )
        .sort((a, b) =>
          sortDesc ? +new Date(b.date) - +new Date(a.date) : +new Date(a.date) - +new Date(b.date),
        ),
    [query, status, sortDesc],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / perPage));
  const shown = filtered.slice((page - 1) * perPage, page * perPage);
  const refresh = () => {
    setLoading(true);
    window.setTimeout(() => setLoading(false), 650);
  };
  return (
    <>
      <div className="section-summary">
        <div>
          <span>Settled volume</span>
          <strong>$1.28M</strong>
          <small>+7.2% this month</small>
        </div>
        <div>
          <span>Transactions</span>
          <strong>12,482</strong>
          <small>Across all payment methods</small>
        </div>
        <div>
          <span>Success rate</span>
          <strong>95.7%</strong>
          <small>+1.4% from last month</small>
        </div>
      </div>
      <Card className="data-card">
        <div className="toolbar">
          <div className="search-input">
            <Search size={17} />
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
              placeholder="Search ID, reference, order, customer..."
            />
            {query && (
              <button onClick={() => setQuery("")}>
                <X size={14} />
              </button>
            )}
          </div>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option>All</option>
            <option>Completed</option>
            <option>Pending</option>
            <option>Failed</option>
            <option>Refunded</option>
          </select>
          <button className="secondary-button">
            <Filter size={15} /> Date range
          </button>
          <button className="icon-button" onClick={refresh} aria-label="Refresh">
            <RefreshCcw className={loading ? "spin" : ""} size={16} />
          </button>
        </div>
        <div className="table-title-row">
          <div>
            <h2>All transactions</h2>
            <span>{filtered.length} results</span>
          </div>
          <button className="sort-button" onClick={() => setSortDesc(!sortDesc)}>
            Date {sortDesc ? "↓" : "↑"}
          </button>
        </div>
        {loading ? (
          <LoadingRows />
        ) : shown.length ? (
          <TransactionTable rows={shown} onOpen={openTransaction} />
        ) : (
          <EmptyState
            title="No transactions found"
            text="Try adjusting your search or status filter."
          />
        )}
        <div className="pagination">
          <span>
            Showing {shown.length ? (page - 1) * perPage + 1 : 0}–
            {Math.min(page * perPage, filtered.length)} of {filtered.length}
          </span>
          <div>
            <button disabled={page === 1} onClick={() => setPage(page - 1)}>
              <ChevronLeft size={16} />
            </button>
            {Array.from({ length: pageCount }, (_, i) => (
              <button
                className={page === i + 1 ? "active" : ""}
                key={i}
                onClick={() => setPage(i + 1)}
              >
                {i + 1}
              </button>
            ))}
            <button disabled={page === pageCount} onClick={() => setPage(page + 1)}>
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </Card>
    </>
  );
}

function Reconciliation({ openTransaction }: { openTransaction: (item: Transaction) => void }) {
  const [filter, setFilter] = useState("Needs review");
  const [selected, setSelected] = useState<Transaction | null>(transactions[1]);
  const rows =
    filter === "All"
      ? transactions
      : filter === "Matched"
        ? transactions.filter((t) => t.match === "Matched")
        : transactions.filter((t) => t.match !== "Matched");
  return (
    <>
      <div className="stats-grid stats-grid-six">
        <StatCard label="Matched records" value="11,824" icon={Check} tone="green" />
        <StatCard label="Unmatched" value="142" icon={AlertCircle} tone="red" />
        <StatCard label="Amount mismatches" value="87" icon={CircleDollarSign} tone="amber" />
        <StatCard label="Missing payments" value="63" icon={CreditCard} tone="purple" />
        <StatCard label="Refund issues" value="34" icon={RefreshCcw} tone="red" />
        <StatCard label="Success rate" value="94.7%" icon={ShieldCheck} tone="navy" />
      </div>
      <div className="tabs">
        {["Needs review", "Matched", "All"].map((item) => (
          <button
            key={item}
            className={filter === item ? "active" : ""}
            onClick={() => setFilter(item)}
          >
            {item}
            {item === "Needs review" && <span>6</span>}
          </button>
        ))}
      </div>
      <div className="recon-layout">
        <Card className="record-list">
          <div className="record-list-head">
            <div className="search-input small">
              <Search size={15} />
              <input placeholder="Search records..." />
            </div>
            <button className="icon-button">
              <Filter size={15} />
            </button>
          </div>
          {rows.map((item) => (
            <button
              key={item.id}
              className={`record-item ${selected?.id === item.id ? "selected" : ""}`}
              onClick={() => setSelected(item)}
            >
              <div>
                <span className="record-id">{item.id}</span>
                <small>
                  {item.orderId} · {formatDate(item.date)}
                </small>
              </div>
              <div>
                <strong>{formatMoney(item.amount)}</strong>
                <StatusBadge value={item.match} />
              </div>
            </button>
          ))}
        </Card>
        {selected ? (
          <Card className="comparison-card">
            <CardHeader
              title="Record comparison"
              caption={`${selected.id} · ${selected.orderId}`}
              action={
                <button className="secondary-button" onClick={() => openTransaction(selected)}>
                  Open transaction <ChevronRight size={14} />
                </button>
              }
            />
            <div className="comparison-head">
              <span>Field</span>
              <span>PayPal record</span>
              <span>Merchant record</span>
            </div>
            {[
              ["Reference", selected.paypalRef, selected.orderId, "match"],
              ["Customer", selected.customer, selected.customer, "match"],
              [
                "Amount",
                formatMoney(selected.amount),
                selected.merchantAmount === undefined
                  ? "Missing"
                  : formatMoney(selected.merchantAmount),
                selected.merchantAmount === selected.amount ? "match" : "different",
              ],
              [
                "Payment status",
                selected.status,
                selected.merchantStatus || "Missing",
                (selected.status === "Completed" && selected.merchantStatus === "Paid") ||
                selected.status === selected.merchantStatus
                  ? "match"
                  : "different",
              ],
              [
                "Currency",
                selected.currency,
                selected.merchantAmount === undefined ? "Missing" : selected.currency,
                selected.merchantAmount === undefined ? "missing" : "match",
              ],
              [
                "Transaction date",
                formatDate(selected.date, true),
                formatDate(selected.date, true),
                "match",
              ],
            ].map(([label, paypal, merchant, state]) => (
              <div className={`comparison-row state-${state}`} key={label}>
                <strong>{label}</strong>
                <span>{paypal}</span>
                <span>
                  {merchant}
                  {state === "match" ? <Check size={15} /> : <AlertCircle size={15} />}
                </span>
              </div>
            ))}
            {selected.match !== "Matched" && (
              <div className="ai-callout">
                <div className="ai-callout-icon">
                  <Sparkles size={18} />
                </div>
                <div>
                  <strong>AI reconciliation insight</strong>
                  <p>
                    {selected.match === "Amount mismatch"
                      ? `The merchant record is ${formatMoney(Math.abs(selected.amount - (selected.merchantAmount || 0)))} lower than the PayPal settlement. This may be a late surcharge or an unapplied adjustment.`
                      : "The systems disagree on this payment. Review recent webhook delivery events before changing the merchant record."}
                  </p>
                </div>
                <button>Investigate</button>
              </div>
            )}
          </Card>
        ) : (
          <EmptyState title="Select a record" text="Choose a reconciliation record to compare." />
        )}
      </div>
    </>
  );
}

function Investigations({
  openInvestigation,
}: {
  openInvestigation: (item: Investigation) => void;
}) {
  const [filter, setFilter] = useState("All");
  const list =
    filter === "All" ? investigations : investigations.filter((item) => item.status === filter);
  return (
    <>
      <div className="investigation-banner">
        <div className="banner-icon">
          <Bot size={23} />
        </div>
        <div>
          <strong>AI investigation center</strong>
          <p>
            PayRecon continuously analyzes discrepancies, event patterns, and payment states to
            surface likely root causes.
          </p>
        </div>
        <div className="ai-status">
          <span /> AI analysis active
        </div>
      </div>
      <div className="stats-grid stats-grid-four">
        <StatCard label="Open investigations" value="24" icon={FileSearch} tone="red" />
        <StatCard label="Awaiting review" value="11" icon={Clock3} tone="amber" />
        <StatCard label="Resolved this month" value="86" change="18%" icon={Check} tone="green" />
        <StatCard label="Avg. resolution time" value="3.2h" icon={Zap} tone="blue" />
      </div>
      <div className="tabs">
        {["All", "Open", "Reviewing", "Resolved"].map((item) => (
          <button
            className={filter === item ? "active" : ""}
            onClick={() => setFilter(item)}
            key={item}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="investigation-grid">
        {list.map((item) => (
          <button
            className="investigation-card"
            key={item.id}
            onClick={() => openInvestigation(item)}
          >
            <div className="investigation-top">
              <StatusBadge value={item.severity} />
              <span>{item.id}</span>
              <ChevronRight size={17} />
            </div>
            <h3>{item.category}</h3>
            <p>{item.summary}</p>
            <div className="investigation-meta">
              <span>
                <CreditCard size={14} />
                {item.transactionId}
              </span>
              <StatusBadge value={item.status} />
            </div>
            <div className="mini-ai">
              <Sparkles size={14} />
              <span>Root cause identified with 92% confidence</span>
            </div>
          </button>
        ))}
      </div>
    </>
  );
}

const initialNodes: Node[] = [
  {
    id: "1",
    position: { x: 0, y: 110 },
    data: {
      label: (
        <FlowNode
          icon={<CreditCard />}
          title="PayPal event"
          meta="10:42:01 · COMPLETED"
          tone="blue"
        />
      ),
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { border: 0, padding: 0, width: 210, background: "transparent" },
  },
  {
    id: "2",
    position: { x: 280, y: 110 },
    data: {
      label: (
        <FlowNode icon={<Zap />} title="Payment processing" meta="10:42:02 · SUCCESS" tone="navy" />
      ),
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { border: 0, padding: 0, width: 210, background: "transparent" },
  },
  {
    id: "3",
    position: { x: 560, y: 110 },
    data: {
      label: (
        <FlowNode
          icon={<WalletCards />}
          title="Database storage"
          meta="10:42:02 · STORED"
          tone="green"
        />
      ),
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { border: 0, padding: 0, width: 210, background: "transparent" },
  },
  {
    id: "4",
    position: { x: 840, y: 110 },
    data: {
      label: (
        <FlowNode
          icon={<RefreshCcw />}
          title="Reconciliation"
          meta="10:43:10 · MISMATCH"
          tone="amber"
        />
      ),
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { border: 0, padding: 0, width: 210, background: "transparent" },
  },
  {
    id: "5",
    position: { x: 1120, y: 110 },
    data: {
      label: (
        <FlowNode icon={<Bot />} title="AI investigation" meta="10:43:12 · OPENED" tone="purple" />
      ),
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { border: 0, padding: 0, width: 210, background: "transparent" },
  },
];
const initialEdges: Edge[] = [1, 2, 3, 4].map((i) => ({
  id: `e${i}`,
  source: `${i}`,
  target: `${i + 1}`,
  animated: i === 3,
  markerEnd: { type: MarkerType.ArrowClosed, color: "#60A5FA" },
  style: { stroke: "#60A5FA", strokeWidth: 2 },
}));

function FlowNode({
  icon,
  title,
  meta,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  meta: string;
  tone: string;
}) {
  return (
    <div className={`flow-node flow-${tone}`}>
      <div className="flow-icon">{icon}</div>
      <div>
        <strong>{title}</strong>
        <span>{meta}</span>
      </div>
    </div>
  );
}

function Lineage({ openTransaction }: { openTransaction: (item: Transaction) => void }) {
  const [selectedId, setSelectedId] = useState(transactions[1].id);
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);
  const selected = transactions.find((item) => item.id === selectedId) || transactions[1];
  return (
    <>
      <div className="lineage-selector">
        <div>
          <label>Transaction</label>
          <div className="search-input">
            <Search size={16} />
            <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
              {transactions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id} · {item.customer}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="lineage-summary">
          <span>
            <i className="online-dot" />5 systems traced
          </span>
          <span>
            Journey time <strong>1m 11s</strong>
          </span>
          <button className="secondary-button" onClick={() => openTransaction(selected)}>
            View details
          </button>
        </div>
      </div>
      <Card className="flow-card">
        <div className="flow-toolbar">
          <div>
            <strong>Payment journey</strong>
            <span>
              {selected.id} · {selected.paypalRef}
            </span>
          </div>
          <div>
            <span className="flow-hint">Drag to explore · scroll to zoom</span>
          </div>
        </div>
        <div className="flow-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            fitView
            minZoom={0.5}
            maxZoom={1.5}
            attributionPosition="bottom-left"
          >
            <Background color="#CBD5E1" gap={22} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor="#60A5FA" maskColor="rgba(248,250,252,.72)" />
          </ReactFlow>
        </div>
      </Card>
      <div className="event-strip">
        {[
          "Payment captured",
          "Webhook received",
          "Record stored",
          "Mismatch detected",
          "Investigation opened",
        ].map((item, index) => (
          <div key={item}>
            <span>{index + 1}</span>
            <strong>{item}</strong>
            <small>
              10:{index === 0 ? "42:01" : index < 3 ? "42:02" : "43:1" + (index - 3) * 2}
            </small>
          </div>
        ))}
      </div>
    </>
  );
}

function SettingsPage() {
  const [saved, setSaved] = useState(false);
  const [toggles, setToggles] = useState({
    discrepancies: true,
    investigations: true,
    weekly: false,
    sounds: false,
    auto: true,
  });
  const toggle = (key: keyof typeof toggles) => setToggles({ ...toggles, [key]: !toggles[key] });
  return (
    <div className="settings-layout">
      <Card className="settings-nav">
        <button className="active">
          <UserRound size={17} />
          Profile
        </button>
        <button>
          <Bell size={17} />
          Notifications
        </button>
        <button>
          <SlidersHorizontal size={17} />
          Preferences
        </button>
        <button>
          <ShieldCheck size={17} />
          Security
        </button>
      </Card>
      <div className="settings-content">
        <Card>
          <CardHeader
            title="Profile information"
            caption="Update your personal details and workspace role."
          />
          <div className="profile-row">
            <div className="profile-avatar large">AM</div>
            <div>
              <strong>Alex Morgan</strong>
              <span>Finance Operations Lead</span>
            </div>
            <button className="secondary-button">Change photo</button>
          </div>
          <div className="form-grid">
            <label>
              First name
              <input defaultValue="Alex" />
            </label>
            <label>
              Last name
              <input defaultValue="Morgan" />
            </label>
            <label>
              Email address
              <input defaultValue="alex.morgan@payrecon.io" />
            </label>
            <label>
              Role
              <input defaultValue="Finance Operations Lead" />
            </label>
          </div>
        </Card>
        <Card>
          <CardHeader
            title="Notification preferences"
            caption="Choose which events should notify you."
          />
          <SettingToggle
            title="Critical discrepancies"
            text="Alert me when high-value or critical mismatches are detected."
            active={toggles.discrepancies}
            onClick={() => toggle("discrepancies")}
          />
          <SettingToggle
            title="Investigation updates"
            text="Notify me when an investigation changes status."
            active={toggles.investigations}
            onClick={() => toggle("investigations")}
          />
          <SettingToggle
            title="Weekly reconciliation summary"
            text="Receive a weekly performance digest by email."
            active={toggles.weekly}
            onClick={() => toggle("weekly")}
          />
          <SettingToggle
            title="Interface sounds"
            text="Play a sound for urgent alerts."
            active={toggles.sounds}
            onClick={() => toggle("sounds")}
          />
        </Card>
        <Card>
          <CardHeader
            title="Application settings"
            caption="Configure reconciliation behavior for this workspace."
          />
          <SettingToggle
            title="Automatic reconciliation"
            text="Run reconciliation when new PayPal events arrive."
            active={toggles.auto}
            onClick={() => toggle("auto")}
          />
          <div className="form-grid">
            <label>
              Default currency
              <select defaultValue="USD">
                <option>USD — US Dollar</option>
                <option>EUR — Euro</option>
                <option>GBP — Pound Sterling</option>
              </select>
            </label>
            <label>
              Timezone
              <select defaultValue="Eastern">
                <option>Eastern Time (US & Canada)</option>
                <option>Pacific Time (US & Canada)</option>
                <option>UTC</option>
              </select>
            </label>
          </div>
        </Card>
        <div className="settings-actions">
          {saved && (
            <span>
              <Check size={15} />
              Changes saved
            </span>
          )}
          <button
            className="primary-button"
            onClick={() => {
              setSaved(true);
              window.setTimeout(() => setSaved(false), 2000);
            }}
          >
            Save changes
          </button>
        </div>
      </div>
    </div>
  );
}

function SettingToggle({
  title,
  text,
  active,
  onClick,
}: {
  title: string;
  text: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
      <button
        aria-label={`Toggle ${title}`}
        className={`toggle ${active ? "on" : ""}`}
        onClick={onClick}
      >
        <span />
      </button>
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="loading-rows">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <div>
        <Search size={22} />
      </div>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function TransactionDetail({
  item,
  onClose,
  openInvestigation,
}: {
  item: Transaction;
  onClose: () => void;
  openInvestigation: (item: Investigation) => void;
}) {
  const linked = investigations.find((inv) => inv.transactionId === item.id);
  return (
    <div className="detail-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="detail-panel">
        <div className="detail-head">
          <button className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
          <div>
            <span>Transaction details</span>
            <h2>{item.id}</h2>
          </div>
          <StatusBadge value={item.status} />
        </div>
        <div className="detail-body">
          <div className="detail-amount">
            <span>Payment amount</span>
            <strong>{formatMoney(item.amount)}</strong>
            <small>
              {item.currency} · {item.method}
            </small>
          </div>
          <DetailSection title="Transaction information">
            <DetailGrid
              items={[
                ["PayPal reference", item.paypalRef],
                ["Merchant order", item.orderId],
                ["Customer", item.customer],
                ["Processed", formatDate(item.date, true)],
              ]}
            />
          </DetailSection>
          <DetailSection title="Reconciliation result">
            <div className="recon-result">
              <StatusBadge value={item.match} />
              <span>Last checked 14 minutes ago</span>
            </div>
            {item.match !== "Matched" && (
              <p className="detail-note">
                PayPal and merchant records require review. Open the reconciliation workspace for a
                field-level comparison.
              </p>
            )}
          </DetailSection>
          <DetailSection title="Event timeline">
            <div className="timeline">
              {[
                ["Payment initiated", "PayPal checkout session created", "10:41:48"],
                [
                  "Payment captured",
                  `${formatMoney(item.amount)} captured successfully`,
                  "10:42:01",
                ],
                ["Webhook received", "PAYMENT.CAPTURE.COMPLETED", "10:42:02"],
                ["Reconciliation completed", item.match, "10:43:10"],
              ].map(([title, text, time], i) => (
                <div key={title} className="timeline-item">
                  <span className={i === 3 && item.match !== "Matched" ? "warning" : ""}>
                    {i === 3 && item.match !== "Matched" ? (
                      <AlertCircle size={13} />
                    ) : (
                      <Check size={13} />
                    )}
                  </span>
                  <div>
                    <strong>{title}</strong>
                    <p>{text}</p>
                  </div>
                  <time>{time}</time>
                </div>
              ))}
            </div>
          </DetailSection>
          <DetailSection title="Investigation history">
            {linked ? (
              <button className="linked-investigation" onClick={() => openInvestigation(linked)}>
                <div>
                  <StatusBadge value={linked.severity} />
                  <strong>
                    {linked.id} · {linked.category}
                  </strong>
                </div>
                <ChevronRight size={17} />
              </button>
            ) : (
              <div className="no-investigation">
                <Check size={16} /> No investigations linked to this transaction.
              </div>
            )}
          </DetailSection>
        </div>
      </aside>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function DetailGrid({ items }: { items: string[][] }) {
  return (
    <div className="detail-grid">
      {items.map(([key, value]) => (
        <div key={key}>
          <span>{key}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function InvestigationDetail({
  item,
  onClose,
  openTransaction,
}: {
  item: Investigation;
  onClose: () => void;
  openTransaction: (item: Transaction) => void;
}) {
  const tx = transactions.find((t) => t.id === item.transactionId)!;
  return (
    <div className="detail-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="detail-panel wide">
        <div className="detail-head">
          <button className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
          <div>
            <span>AI investigation</span>
            <h2>{item.id}</h2>
          </div>
          <StatusBadge value={item.status} />
        </div>
        <div className="detail-body">
          <div className="investigation-detail-title">
            <div>
              <StatusBadge value={item.severity} />
              <h2>{item.category}</h2>
              <p>{item.summary}</p>
            </div>
            <button className="secondary-button" onClick={() => openTransaction(tx)}>
              {tx.id}
              <ChevronRight size={14} />
            </button>
          </div>
          <div className="fact-label">
            <ShieldCheck size={14} />
            Confirmed system facts
          </div>
          <DetailGrid
            items={[
              ["PayPal amount", formatMoney(tx.amount)],
              ["Merchant amount", tx.merchantAmount ? formatMoney(tx.merchantAmount) : "Missing"],
              ["PayPal status", tx.status],
              ["Merchant status", tx.merchantStatus || "Missing"],
            ]}
          />
          <div className="ai-analysis">
            <div className="ai-analysis-head">
              <Sparkles size={18} />
              <div>
                <strong>AI-generated analysis</strong>
                <span>92% confidence · Review before action</span>
              </div>
            </div>
            <h3>Likely root cause</h3>
            <p>{item.rootCause}</p>
            <h3>Supporting evidence</h3>
            <ul>
              <li>
                Event timestamps show the PayPal update arrived before the merchant record changed.
              </li>
              <li>Three similar discrepancies were identified in the last 30 days.</li>
              <li>No evidence of duplicate settlement was found.</li>
            </ul>
          </div>
          <DetailSection title="Event timeline">
            <div className="timeline">
              <div className="timeline-item">
                <span>
                  <Check size={13} />
                </span>
                <div>
                  <strong>Payment event received</strong>
                  <p>PayPal record ingested</p>
                </div>
                <time>10:42</time>
              </div>
              <div className="timeline-item">
                <span className="warning">
                  <AlertCircle size={13} />
                </span>
                <div>
                  <strong>Discrepancy detected</strong>
                  <p>{item.category}</p>
                </div>
                <time>10:43</time>
              </div>
              <div className="timeline-item">
                <span>
                  <Sparkles size={13} />
                </span>
                <div>
                  <strong>AI analysis completed</strong>
                  <p>Root cause and resolution generated</p>
                </div>
                <time>10:44</time>
              </div>
            </div>
          </DetailSection>
          <div className="recommendation">
            <div>
              <Bot size={20} />
            </div>
            <div>
              <span>Recommended next action</span>
              <strong>{item.recommendation}</strong>
            </div>
          </div>
          <div className="detail-actions">
            <button className="secondary-button">Mark as reviewed</button>
            <button className="primary-button">Resolve investigation</button>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [selectedInvestigation, setSelectedInvestigation] = useState<Investigation | null>(null);
  const navigate = useCallback((next: Page) => {
    setPage(next);
    setMobileOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);
  const openInvestigation = (item: Investigation) => {
    setSelectedTransaction(null);
    setSelectedInvestigation(item);
  };
  const openTransaction = (item: Transaction) => {
    setSelectedInvestigation(null);
    setSelectedTransaction(item);
  };
  return (
    <div className="app-shell">
      {mobileOpen && (
        <button
          className="mobile-backdrop"
          onClick={() => setMobileOpen(false)}
          aria-label="Close menu"
        />
      )}
      <aside
        className={`sidebar ${collapsed ? "collapsed" : ""} ${mobileOpen ? "mobile-open" : ""}`}
      >
        <div className="brand">
          <div className="brand-mark">
            <span>P</span>
          </div>
          {!collapsed && (
            <div>
              <strong>PayRecon</strong>
              <small>AI</small>
            </div>
          )}
          <button className="mobile-close" onClick={() => setMobileOpen(false)}>
            <X size={18} />
          </button>
        </div>
        <div className="workspace">
          {!collapsed && (
            <>
              <span>Workspace</span>
              <strong>Acme Commerce</strong>
            </>
          )}
          <ChevronDown size={15} />
        </div>
        <nav>
          {navItems.map(({ id, label, icon: Icon, count }) => (
            <button
              key={id}
              title={collapsed ? label : undefined}
              className={page === id ? "active" : ""}
              onClick={() => navigate(id)}
            >
              <Icon size={19} />
              {!collapsed && (
                <>
                  <span>{label}</span>
                  {count && <b>{count}</b>}
                </>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button>
            <HelpCircle size={19} />
            {!collapsed && <span>Help & support</span>}
          </button>
          <button className="collapse-button" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}{" "}
            {!collapsed && <span>Collapse sidebar</span>}
          </button>
        </div>
      </aside>
      <div className={`main-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
        <header className="topbar">
          <button className="menu-button" onClick={() => setMobileOpen(true)}>
            <Menu size={20} />
          </button>
          <div className="global-search">
            <Search size={17} />
            <input placeholder="Search transactions, orders, investigations..." />
            <kbd>⌘ K</kbd>
          </div>
          <div className="top-actions">
            <div className="popover-wrap">
              <button
                className="icon-button bell-button"
                onClick={() => setNotificationsOpen(!notificationsOpen)}
              >
                <Bell size={18} />
                <span />
              </button>
              {notificationsOpen && (
                <div className="popover notifications">
                  <div>
                    <strong>Notifications</strong>
                    <button onClick={() => setNotificationsOpen(false)}>
                      <X size={15} />
                    </button>
                  </div>
                  <p>
                    <i className="critical-ping" />
                    Critical mismatch detected on TXN-88417<small>8 minutes ago</small>
                  </p>
                  <p>
                    <i />
                    Investigation INV-2477 was resolved<small>1 hour ago</small>
                  </p>
                </div>
              )}
            </div>
            <div className="top-divider" />
            <div className="popover-wrap">
              <button className="profile-button" onClick={() => setProfileOpen(!profileOpen)}>
                <div className="profile-avatar">AM</div>
                <div>
                  <strong>Alex Morgan</strong>
                  <span>Finance Ops</span>
                </div>
                <ChevronDown size={14} />
              </button>
              {profileOpen && (
                <div className="popover profile-menu">
                  <button onClick={() => navigate("settings")}>
                    <UserRound size={15} />
                    Profile settings
                  </button>
                  <button>
                    <HelpCircle size={15} />
                    Support center
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main>
          <div className="page-head">
            <div>
              <div className="breadcrumbs">
                <span>PayRecon</span>
                <ChevronRight size={13} />
                <strong>{titles[page].title}</strong>
              </div>
              <h1>{titles[page].title}</h1>
              <p>{titles[page].subtitle}</p>
            </div>
            {page === "overview" && (
              <div className="last-updated">
                <span className="online-dot" />
                Live data · Updated just now
                <button className="icon-button">
                  <RefreshCcw size={15} />
                </button>
              </div>
            )}
          </div>
          {page === "overview" && (
            <Overview
              navigate={navigate}
              openTransaction={openTransaction}
              openInvestigation={openInvestigation}
            />
          )}
          {page === "payments" && <Payments openTransaction={openTransaction} />}
          {page === "reconciliation" && <Reconciliation openTransaction={openTransaction} />}
          {page === "investigations" && <Investigations openInvestigation={openInvestigation} />}
          {page === "lineage" && <Lineage openTransaction={openTransaction} />}
          {page === "settings" && <SettingsPage />}
        </main>
      </div>
      {selectedTransaction && (
        <TransactionDetail
          item={selectedTransaction}
          onClose={() => setSelectedTransaction(null)}
          openInvestigation={openInvestigation}
        />
      )}
      {selectedInvestigation && (
        <InvestigationDetail
          item={selectedInvestigation}
          onClose={() => setSelectedInvestigation(null)}
          openTransaction={openTransaction}
        />
      )}
    </div>
  );
}
