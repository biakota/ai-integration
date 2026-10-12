const LABELS = {
  unparsed: "Not read",
  needs_review: "Needs review",
  parsed: "Extracted",
  confirmed: "Confirmed",
};

export default function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{LABELS[status] || status}</span>;
}
