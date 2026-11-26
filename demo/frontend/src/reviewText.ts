/** Agent review presentation only; raw Tool data and Agent Cards stay unchanged. */
function label(key: string): string {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()).replace(/\bId\b/g, "ID");
}

function scalar(value: unknown): string {
  if (value === null) return "Not provided";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function markdown(value: unknown, level = 2): string {
  if (Array.isArray(value)) return value.map((item, index) => item !== null && typeof item === "object"
    ? "### Item " + (index + 1) + "\n\n" + markdown(item, 4)
    : "- " + scalar(item)).join("\n");
  if (value !== null && typeof value === "object") return Object.entries(value).map(([key, item]) => {
    if (level >= 3 && (item === null || typeof item !== "object")) return "- **" + label(key) + ":** " + scalar(item);
    return "#".repeat(Math.min(level, 6)) + " " + label(key) + "\n\n" + markdown(item, level + 1);
  }).join("\n\n");
  return scalar(value);
}

export function readableChatText(body: string): string {
  const candidate = body.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  if (!candidate.startsWith("{") && !/^\[\s*(?:[\{"\d\]-]|$)/.test(candidate)) return body;
  try {
    const value: unknown = JSON.parse(candidate);
    if (value !== null && typeof value === "object") return markdown(value) || "No review details were returned.";
  } catch {
    // Partial SSE content must not flash serialized JSON into a Chat bubble.
    if (!/[}\]]$/.test(candidate)) return "Preparing the review…";
    return "The Agent review could not be displayed. Its original response is available in the trace.";
  }
  return body;
}

/** Keep Agent speech visible; collapse only the explicitly named review sections. */
export function splitReviewDetails(body: string): { answer: string; details: { title: string; body: string }[] } {
  const reviewTitles = new Set(["verified facts", "operational assessment", "unresolved technical details"]);
  const answer: string[] = [];
  const details: { title: string; body: string }[] = [];
  let active: { title: string; lines: string[]; level: number } | undefined;
  let fence = "";
  const flush = () => {
    if (active) details.push({ title: active.title, body: active.lines.join("\n").trim() });
    active = undefined;
  };
  for (const line of body.split("\n")) {
    const marker = line.trim().match(/^(\x60{3,}|~{3,})/);
    const heading = !fence ? line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/) : null;
    if (heading && active && heading[1].length <= active.level) flush();
    const title = heading?.[2].replace(/\*\*/g, "").trim();
    const titles = title?.toLowerCase().split(/\s*,\s*|\s+and\s+/);
    if (heading && !active && titles?.every((item) => reviewTitles.has(item))) {
      active = { title: title!, lines: [], level: heading[1].length };
    } else if (active) active.lines.push(line);
    else answer.push(line);
    if (marker && !fence) fence = marker[1];
    else if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = "";
  }
  flush();
  return { answer: answer.join("\n").trim(), details };
}
