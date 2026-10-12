const money = new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD" });
const number = new Intl.NumberFormat("fr-CA", { maximumFractionDigits: 2 });

export function formatMoney(value) {
  return value == null ? "—" : money.format(Number(value));
}

export function formatNumber(value, unit) {
  if (value == null) return "—";
  return `${number.format(Number(value))} ${unit === "m3" ? "m³" : unit}`;
}

// end_billing_period is exclusive, so end - start is the number of days billed.
export function periodDays(start, end) {
  if (!start || !end) return null;
  return Math.round((new Date(end) - new Date(start)) / 86_400_000);
}

export function formatPeriod(start, end) {
  if (!start || !end) return "—";
  return `${start} → ${end} (${periodDays(start, end)} days)`;
}

export const UTILITIES = [
  { value: "hydro_quebec", label: "Hydro-Québec" },
  { value: "gaz_boreal", label: "Gaz Boréal" },
  { value: "ottawa_valley_power", label: "Ottawa Valley Power & Light" },
  { value: "other", label: "Other" },
];

export function utilityLabel(value) {
  return UTILITIES.find((u) => u.value === value)?.label || value || "Unknown";
}
