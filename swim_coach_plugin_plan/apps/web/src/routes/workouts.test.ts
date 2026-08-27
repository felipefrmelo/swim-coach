import { describe, expect, it } from "vitest";

import { formatPace, parsePace } from "./workout-pace";

describe("workout pace fields", () => {
  it("formats canonical seconds per 100 m as a duration", () => {
    expect(formatPace(135)).toBe("2:15");
    expect(formatPace(150)).toBe("2:30");
  });

  it("parses valid durations and rejects incomplete or invalid values", () => {
    expect(parsePace("2:15")).toBe(135);
    expect(parsePace(" 10:05 ")).toBe(605);
    expect(parsePace("2:75")).toBeNull();
    expect(parsePace("2")).toBeNull();
    expect(parsePace("0:00")).toBeNull();
  });
});
