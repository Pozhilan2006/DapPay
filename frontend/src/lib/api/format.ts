export function formatPaymentAmount(
  amount: string | null,
  currency: string | null,
): string {
  if (amount === null) {
    return `Amount unavailable${currency ? ` (${currency})` : ""}`;
  }
  const [integer, fraction] = amount.split(".");
  const grouped = /[eE]/.test(amount)
    ? amount
    : integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const formatted =
    fraction === undefined || /[eE]/.test(amount)
      ? grouped
      : `${grouped}.${fraction}`;
  return `${formatted} ${currency ?? "(currency unavailable)"}`;
}
