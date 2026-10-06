// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmMaintenanceRepair, listApplications } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("Hub API credential boundaries", () => {
  it("does not attach the platform admin token to ordinary application requests", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await listApplications();

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-Lyra-Admin-Token"]).toBeUndefined();
  });

  it("attaches the platform admin token to explicit maintenance operations", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ data: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await confirmMaintenanceRepair(
      "gateway",
      { action: "restore_last_good", expected_revision: 4, confirmed: true },
      "stable-repair-key",
    );

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-Lyra-Admin-Token"]).toBe("hub-admin-secret");
    expect(headers["Idempotency-Key"]).toBe("stable-repair-key");
  });
});
