import { ApiError } from "./errors";
import type { MerchantOrder, PaymentCapture, WebhookSummary } from "./types";

export type AccessTokenProvider = () => string | null | Promise<string | null>;

export interface ReconciliationStatus {
  status: string;
  message: string;
}

export interface LineageStatus {
  status: string;
  message: string;
}

let accessTokenProvider: AccessTokenProvider | null = null;

/** Register the access-token getter supplied by a trusted identity provider. */
export function configureAccessTokenProvider(provider: AccessTokenProvider | null): void {
  accessTokenProvider = provider;
}

export function isAccessTokenProviderConfigured(): boolean {
  return accessTokenProvider !== null;
}

async function getAccessToken(): Promise<string | null> {
  if (!accessTokenProvider) return null;
  const token = await accessTokenProvider();
  return typeof token === "string" && token.trim() ? token.trim() : null;
}

function apiBaseUrl(): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "");
  if (!baseUrl) {
    throw new ApiError("NEXT_PUBLIC_API_BASE_URL is not configured.", "configuration");
  }
  return baseUrl;
}

function preserveDecimalJsonNumbers(raw: string): string {
  // JSON.parse otherwise turns PostgreSQL Numeric values into binary floats.
  return raw.replace(
    /(\"(?:amount|refunded_amount)\"\s*:\s*)(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    "$1\"$2\"",
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function requestJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const baseUrl = apiBaseUrl();
  const token = await getAccessToken();
  const headers = new Headers({ Accept: "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: "GET",
      headers,
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("The payment API could not be reached.", "network");
  }

  const body = await response.text();
  let parsed: unknown = null;
  if (body) {
    try {
      parsed = JSON.parse(preserveDecimalJsonNumbers(body)) as unknown;
    } catch {
      if (response.ok) {
        throw new ApiError("The API returned invalid JSON.", "response", response.status);
      }
    }
  }

  if (!response.ok) {
    const detail = isRecord(parsed) && typeof parsed.detail === "string" ? parsed.detail : "";
    throw new ApiError(
      detail || `PayRecon API request failed with HTTP ${response.status}.`,
      "http",
      response.status,
    );
  }
  return parsed;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ApiError(`The API response is missing ${field}.`, "response");
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") {
    throw new ApiError(`The API response has an invalid ${field}.`, "response");
  }
  return value;
}

function decimalString(value: unknown, field: string, nullable = false): string | null {
  if (nullable && (value === null || value === undefined)) return null;
  if (typeof value !== "string" || !/^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value)) {
    throw new ApiError(`The API response has an invalid ${field}.`, "response");
  }
  return value;
}

function parsePayment(value: unknown): PaymentCapture {
  if (!isRecord(value)) throw new ApiError("Invalid payment response.", "response");
  return {
    payment_id: requiredString(value.payment_id, "payment_id"),
    order_id: requiredString(value.order_id, "order_id"),
    status: requiredString(value.status, "status"),
    amount: decimalString(value.amount, "amount", true),
    refunded_amount: decimalString(value.refunded_amount, "refunded_amount")!,
    currency: nullableString(value.currency, "currency"),
    paypal_created_at: nullableString(value.paypal_created_at, "paypal_created_at"),
    paypal_updated_at: nullableString(value.paypal_updated_at, "paypal_updated_at"),
  };
}

function parseOrder(value: unknown): MerchantOrder {
  if (!isRecord(value)) throw new ApiError("Invalid order response.", "response");
  return {
    order_id: requiredString(value.order_id, "order_id"),
    merchant_reference: nullableString(value.merchant_reference, "merchant_reference"),
    invoice_id: nullableString(value.invoice_id, "invoice_id"),
    amount: decimalString(value.amount, "amount", true),
    currency: nullableString(value.currency, "currency"),
    intent: nullableString(value.intent, "intent"),
    status: nullableString(value.status, "status"),
    paypal_created_at: nullableString(value.paypal_created_at, "paypal_created_at"),
    paypal_updated_at: nullableString(value.paypal_updated_at, "paypal_updated_at"),
    created_at: requiredString(value.created_at, "created_at"),
    updated_at: requiredString(value.updated_at, "updated_at"),
  };
}

export async function listPayments(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<PaymentCapture[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const result = await requestJson(`/api/payments?${query.toString()}`, signal);
  if (!Array.isArray(result)) throw new ApiError("Invalid payments list response.", "response");
  return result.map(parsePayment);
}

export async function getReconciliationStatus(
  signal?: AbortSignal,
): Promise<ReconciliationStatus> {
  const result = await requestJson("/api/reconciliation", signal);
  if (
    !isRecord(result) ||
    typeof result.status !== "string" ||
    typeof result.message !== "string"
  ) {
    throw new ApiError("Invalid reconciliation status response.", "response");
  }
  return { status: result.status, message: result.message };
}

function parseWebhook(value: unknown): WebhookSummary {
  if (!isRecord(value)) throw new ApiError("Invalid webhook response.", "response");
  return {
    event_id: requiredString(value.event_id, "event_id"),
    event_type: requiredString(value.event_type, "event_type"),
    resource_type: nullableString(value.resource_type, "resource_type"),
    resource_id: nullableString(value.resource_id, "resource_id"),
    occurred_at: nullableString(value.occurred_at, "occurred_at"),
    received_at: requiredString(value.received_at, "received_at"),
    verification_status: requiredString(value.verification_status, "verification_status"),
    processing_status: requiredString(value.processing_status, "processing_status"),
    processing_error: nullableString(value.processing_error, "processing_error"),
  };
}

export async function listWebhooks(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<WebhookSummary[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const result = await requestJson(`/api/webhooks?${query.toString()}`, signal);
  if (!Array.isArray(result)) throw new ApiError("Invalid webhook list response.", "response");
  return result.map(parseWebhook);
}

export async function getLineageStatus(signal?: AbortSignal): Promise<LineageStatus> {
  const result = await requestJson("/api/lineage", signal);
  if (!isRecord(result) || typeof result.status !== "string" || typeof result.message !== "string") {
    throw new ApiError("Invalid lineage status response.", "response");
  }
  return { status: result.status, message: result.message };
}

export async function getPayment(
  paymentId: string,
  signal?: AbortSignal,
): Promise<PaymentCapture> {
  return parsePayment(await requestJson(`/api/payments/${encodeURIComponent(paymentId)}`, signal));
}

export async function getOrder(
  orderId: string,
  signal?: AbortSignal,
): Promise<MerchantOrder> {
  return parseOrder(await requestJson(`/api/orders/${encodeURIComponent(orderId)}`, signal));
}
