import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync("public/sw.js", "utf8");

describe("offline safety policy", () => {
  it("only caches the workout read model and marks stale responses", () => {
    expect(source).toContain("SAFE_API");
    expect(source).toContain("/workouts");
    expect(source).toContain('X-Swim-Coach-Offline", "stale');
  });

  it("excludes every controlled action boundary", () => {
    for (const boundary of ["actions", "proposals", "approve", "reject", "publish", "schedule"]) {
      expect(source).toContain(boundary);
    }
    expect(source).toContain("request.method !== \"GET\"");
  });
});
