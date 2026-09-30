import { describe, expect, it } from "vitest";
import { isAllowedBridgeOrigin } from "./workspace-bridge";

describe("workspace bridge", () => {
  it("matches an explicitly allowed child origin", () => {
    expect(
      isAllowedBridgeOrigin("http://127.0.0.1:8000", ["http://127.0.0.1:8000"]),
    ).toBe(true);
  });

  it("rejects origins that were not declared by the application", () => {
    expect(
      isAllowedBridgeOrigin("https://evil.example", ["http://127.0.0.1:8000"]),
    ).toBe(false);
  });
});
