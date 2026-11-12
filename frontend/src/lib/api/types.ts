/** Decimal values from PostgreSQL Numeric fields are kept as strings. */
export type DecimalString = string;

export interface PaymentCapture {
  payment_id: string;
  order_id: string;
  status: string;
  amount: DecimalString | null;
  refunded_amount: DecimalString;
  currency: string | null;
  paypal_created_at: string | null;
  paypal_updated_at: string | null;
}

export interface MerchantOrder {
  order_id: string;
  merchant_reference: string | null;
  invoice_id: string | null;
  amount: DecimalString | null;
  currency: string | null;
  intent: string | null;
  status: string | null;
  paypal_created_at: string | null;
  paypal_updated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebhookSummary {
  event_id: string;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  occurred_at: string | null;
  received_at: string;
  verification_status: string;
  processing_status: string;
  processing_error: string | null;
}

