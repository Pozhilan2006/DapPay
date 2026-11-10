export type PaymentStatus = "Completed" | "Pending" | "Failed" | "Refunded";
export type MatchStatus = "Matched" | "Amount mismatch" | "Status mismatch" | "Missing record";
export type Severity = "Critical" | "High" | "Medium" | "Low";

export interface Transaction {
  id: string;
  paypalRef: string;
  orderId: string;
  amount: number;
  currency: string;
  status: PaymentStatus;
  method: string;
  date: string;
  customer: string;
  match: MatchStatus;
  merchantAmount?: number;
  merchantStatus?: string;
}

export interface Investigation {
  id: string;
  transactionId: string;
  category: string;
  severity: Severity;
  status: "Open" | "Reviewing" | "Resolved";
  summary: string;
  rootCause: string;
  recommendation: string;
}

export const transactions: Transaction[] = [
  {
    id: "TXN-88421",
    paypalRef: "9KJ40298LM",
    orderId: "ORD-10482",
    amount: 1240,
    currency: "USD",
    status: "Completed",
    method: "PayPal Balance",
    date: "2025-05-24T10:42:00",
    customer: "Aperture Labs",
    match: "Matched",
    merchantAmount: 1240,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88420",
    paypalRef: "2PR73419DA",
    orderId: "ORD-10481",
    amount: 789.5,
    currency: "USD",
    status: "Completed",
    method: "Visa •••• 4242",
    date: "2025-05-24T09:18:00",
    customer: "Northstar Inc.",
    match: "Amount mismatch",
    merchantAmount: 749.5,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88419",
    paypalRef: "7HT12530QX",
    orderId: "ORD-10480",
    amount: 214.99,
    currency: "USD",
    status: "Pending",
    method: "Bank transfer",
    date: "2025-05-24T08:51:00",
    customer: "Morrow Studio",
    match: "Status mismatch",
    merchantAmount: 214.99,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88418",
    paypalRef: "3FA91827BZ",
    orderId: "ORD-10479",
    amount: 3500,
    currency: "USD",
    status: "Completed",
    method: "Mastercard •••• 8080",
    date: "2025-05-23T16:35:00",
    customer: "Orbital Systems",
    match: "Matched",
    merchantAmount: 3500,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88417",
    paypalRef: "8WN60142KR",
    orderId: "ORD-10478",
    amount: 425,
    currency: "USD",
    status: "Failed",
    method: "Visa •••• 1934",
    date: "2025-05-23T15:07:00",
    customer: "Kindred Goods",
    match: "Missing record",
    merchantStatus: "Missing",
  },
  {
    id: "TXN-88416",
    paypalRef: "6CJ53018PV",
    orderId: "ORD-10477",
    amount: 1680,
    currency: "USD",
    status: "Refunded",
    method: "PayPal Balance",
    date: "2025-05-23T12:22:00",
    customer: "Elevate Media",
    match: "Status mismatch",
    merchantAmount: 1680,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88415",
    paypalRef: "1KM47820US",
    orderId: "ORD-10476",
    amount: 92.4,
    currency: "USD",
    status: "Completed",
    method: "Visa •••• 6149",
    date: "2025-05-22T18:14:00",
    customer: "Hearth & Co.",
    match: "Matched",
    merchantAmount: 92.4,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88414",
    paypalRef: "4LB20931ME",
    orderId: "ORD-10475",
    amount: 550,
    currency: "USD",
    status: "Completed",
    method: "Amex •••• 1005",
    date: "2025-05-22T14:49:00",
    customer: "Vela Partners",
    match: "Matched",
    merchantAmount: 550,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88413",
    paypalRef: "5NS84027TF",
    orderId: "ORD-10474",
    amount: 1099,
    currency: "USD",
    status: "Completed",
    method: "PayPal Balance",
    date: "2025-05-21T11:03:00",
    customer: "Copperline",
    match: "Amount mismatch",
    merchantAmount: 999,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88412",
    paypalRef: "0PX38174GW",
    orderId: "ORD-10473",
    amount: 75.25,
    currency: "USD",
    status: "Pending",
    method: "Bank transfer",
    date: "2025-05-21T09:37:00",
    customer: "Fieldwork LLC",
    match: "Missing record",
    merchantStatus: "Missing",
  },
  {
    id: "TXN-88411",
    paypalRef: "9AD72016CY",
    orderId: "ORD-10472",
    amount: 2480,
    currency: "USD",
    status: "Completed",
    method: "Visa •••• 4430",
    date: "2025-05-20T17:20:00",
    customer: "Daylight Tech",
    match: "Matched",
    merchantAmount: 2480,
    merchantStatus: "Paid",
  },
  {
    id: "TXN-88410",
    paypalRef: "2ER65083JK",
    orderId: "ORD-10471",
    amount: 319.99,
    currency: "USD",
    status: "Failed",
    method: "Mastercard •••• 6218",
    date: "2025-05-20T13:12:00",
    customer: "Assembly Works",
    match: "Matched",
    merchantAmount: 319.99,
    merchantStatus: "Failed",
  },
];

export const investigations: Investigation[] = [
  {
    id: "INV-2481",
    transactionId: "TXN-88420",
    category: "Amount mismatch",
    severity: "High",
    status: "Open",
    summary: "PayPal settled $40.00 more than the merchant order total.",
    rootCause: "A shipping surcharge was added after the merchant order snapshot was created.",
    recommendation:
      "Confirm the surcharge with the fulfillment team, then update order ORD-10481 before closing.",
  },
  {
    id: "INV-2480",
    transactionId: "TXN-88417",
    category: "Missing record",
    severity: "Critical",
    status: "Reviewing",
    summary: "Payment attempt has no corresponding merchant record.",
    rootCause:
      "The order service timed out before persisting the merchant order while PayPal retained the attempt.",
    recommendation:
      "Verify whether goods were fulfilled. Recreate the order record only after customer identity is confirmed.",
  },
  {
    id: "INV-2479",
    transactionId: "TXN-88416",
    category: "Refund discrepancy",
    severity: "High",
    status: "Open",
    summary: "PayPal shows a completed refund, but the merchant order remains paid.",
    rootCause:
      "The refund webhook was delivered twice and both attempts failed internal validation.",
    recommendation:
      "Mark the order as refunded and replay only the latest validated webhook event.",
  },
  {
    id: "INV-2478",
    transactionId: "TXN-88419",
    category: "Status mismatch",
    severity: "Medium",
    status: "Reviewing",
    summary: "Merchant order is paid while PayPal settlement remains pending.",
    rootCause: "The merchant status advanced on authorization rather than capture.",
    recommendation:
      "Wait for settlement for up to 24 hours; revert the order to authorized if capture fails.",
  },
  {
    id: "INV-2477",
    transactionId: "TXN-88413",
    category: "Amount mismatch",
    severity: "Medium",
    status: "Resolved",
    summary: "A $100.00 discrepancy was detected and resolved.",
    rootCause: "A coupon was applied only in the merchant system.",
    recommendation:
      "Resolved by issuing a partial refund and recording the coupon against the PayPal transaction.",
  },
];

export const activityData = [
  { day: "May 18", successful: 620, failed: 34, pending: 42 },
  { day: "May 19", successful: 710, failed: 41, pending: 28 },
  { day: "May 20", successful: 680, failed: 29, pending: 36 },
  { day: "May 21", successful: 820, failed: 45, pending: 31 },
  { day: "May 22", successful: 780, failed: 32, pending: 44 },
  { day: "May 23", successful: 910, failed: 38, pending: 27 },
  { day: "May 24", successful: 860, failed: 24, pending: 39 },
];

export const reconciliationData = [
  { name: "Matched", value: 94.7, color: "#0B2A4A" },
  { name: "Unmatched", value: 5.3, color: "#60A5FA" },
];

export const formatMoney = (value: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);

export const formatDate = (date: string, includeTime = false) =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    ...(includeTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(new Date(date));
