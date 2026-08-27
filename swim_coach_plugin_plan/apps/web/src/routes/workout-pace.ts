export function formatPace(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  const rounded = Math.max(1, Math.round(seconds));
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}

export function parsePace(value: string) {
  const match = /^(\d+):([0-5]\d)$/.exec(value.trim());
  if (!match) return null;
  const seconds = Number(match[1]) * 60 + Number(match[2]);
  return seconds > 0 ? seconds : null;
}
