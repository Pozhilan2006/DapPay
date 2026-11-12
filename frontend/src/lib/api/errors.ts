export type ApiErrorKind =
  | "http"
  | "network"
  | "configuration"
  | "response";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: ApiErrorKind,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isUnauthorized) {
      return "Sign-in is required to view live payments. Connect your trusted identity provider and try again.";
    }
    if (error.isForbidden) {
      return "Your account does not have permission to view these payments.";
    }
    if (error.isNotFound) {
      return "The requested payment record could not be found.";
    }
    if (error.kind === "network") {
      return "The payment API could not be reached. Check that the backend is running and try again.";
    }
    if (error.kind === "configuration") {
      return "The API URL is not configured. Set NEXT_PUBLIC_API_BASE_URL and restart the frontend.";
    }
    if (error.kind === "response") {
      return "The API returned data that does not match the expected payment format.";
    }
    if (error.status === 503) {
      return "The API is temporarily unavailable. Check backend and database health, then retry.";
    }
    return error.message;
  }
  return "Payments could not be loaded. Try again.";
}
