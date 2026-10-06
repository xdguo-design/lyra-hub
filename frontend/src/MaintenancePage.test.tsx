// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { MaintenancePage } from "./MaintenancePage";
import { click, flushEffects, mount } from "./test-utils";

const overview = {
  data: {
    schedule: { interval_seconds: 300, enabled: true, next_run_at: null, last_run_at: null },
    services: {
      hub: { status: "healthy", checks: { "hub.health": { status: "healthy", checked_at: null } } },
      gateway: { status: "unhealthy", checks: { "gateway.models": { status: "unhealthy", error_code: "TIMEOUT", checked_at: null } } },
      agents: { status: "unknown", checks: {} },
      narrative: { status: "healthy", checks: {} },
      print: { status: "empty_catalog", checks: {} },
    },
    open_alerts: 1,
    agents_available: null,
  },
};
const alert = {
  id: 7,
  service_id: "gateway",
  check_name: "gateway.models",
  error_code: "TIMEOUT",
  severity: "error",
  status: "open",
  consecutive_failures: 2,
  first_occurred_at: "2026-10-03T10:00:00Z",
  last_occurred_at: "2026-10-03T10:05:00Z",
};
const connection = {
  service_id: "gateway",
  base_url: "https://gateway.internal",
  credential_configured: true,
  revision: 4,
  source: "database",
  checked_at: null,
  has_last_good: true,
};

function setupFetch(options?: {
  alerts?: unknown[];
  fail?: { status: number; body: unknown };
  failConfirmOnce?: boolean;
  conflictConfirmOnce?: boolean;
  connectionRevision?: number;
  connectionRevisions?: number[];
  failConnectionsAfterFirst?: boolean;
}) {
  const calls: Array<{ path: string; init: RequestInit }> = [];
  let confirmCount = 0;
  let connectionReadCount = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input).replace("http://localhost:8000", "");
    calls.push({ path, init });
    if (options?.fail && path === "/api/v1/maintenance/overview") {
      return new Response(JSON.stringify(options.fail.body), {
        status: options.fail.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (path === "/api/v1/maintenance/overview") return new Response(JSON.stringify(overview));
    if (path.startsWith("/api/v1/maintenance/alerts?")) return new Response(JSON.stringify({ data: options?.alerts ?? [alert] }));
    if (path === "/api/v1/platform/connections") {
      const revisions = options?.connectionRevisions;
      const readIndex = connectionReadCount++;
      if (options?.failConnectionsAfterFirst && readIndex > 0) {
        return new Response(JSON.stringify({ detail: "connection refresh failed" }), { status: 503 });
      }
      const revision = revisions?.[Math.min(readIndex, revisions.length - 1)]
        ?? options?.connectionRevision
        ?? connection.revision;
      return new Response(JSON.stringify({ data: [{ ...connection, revision }] }));
    }
    if (path === "/api/v1/maintenance/checks") return new Response(JSON.stringify({ data: [] }));
    if (path.endsWith("/acknowledge")) return new Response(JSON.stringify({ data: { ...alert, status: "acknowledged" } }));
    if (path.endsWith("/confirm")) {
      confirmCount += 1;
      if (options?.failConfirmOnce && confirmCount === 1) throw new TypeError("network disconnected");
      if (options?.conflictConfirmOnce && confirmCount === 1) {
        return new Response(JSON.stringify({ detail: { code: "REVISION_CONFLICT" } }), { status: 409 });
      }
      return new Response(JSON.stringify({
        data: { service_id: "gateway", configuration_status: "restored", verification_status: "healthy", revision: 5 },
      }));
    }
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

describe("MaintenancePage", () => {
  it("shows all five services and does not write while loading", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch();
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();

    expect(container.textContent).toContain("Gateway");
    expect(container.textContent).toContain("Agents");
    expect(container.textContent).toContain("Narrative");
    expect(container.textContent).toContain("Print");
    expect(container.textContent).toContain("Lyra Hub");
    expect(calls.every(({ init }) => !init.method || init.method === "GET")).toBe(true);
    expect((calls[0].init.headers as Record<string, string>)["X-Lyra-Admin-Token"]).toBe("hub-admin-secret");

    await act(async () => root.unmount());
  });

  it("runs checks only after the operator clicks the check button", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch();
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();
    expect(calls.some(({ path, init }) => path.endsWith("/checks") && init.method === "POST")).toBe(false);

    const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("立即巡检"));
    expect(button).toBeTruthy();
    await click(button!);
    expect(calls.some(({ path, init }) => path.endsWith("/checks") && init.method === "POST")).toBe(true);
    await act(async () => root.unmount());
  });

  it("acknowledges an alert and requires a second confirmation for repair", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch();
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();

    const acknowledge = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("确认告警"));
    expect(acknowledge).toBeTruthy();
    await click(acknowledge!);
    expect(calls.some(({ path, init }) => path.endsWith("/alerts/7/acknowledge") && init.method === "POST")).toBe(true);

    const repair = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("恢复最近可用配置"));
    expect(repair).toBeTruthy();
    await click(repair!);
    expect(container.textContent).toContain("二次确认");
    expect(calls.some(({ path, init }) => path.endsWith("/repairs/gateway/confirm") && init.method === "POST")).toBe(false);

    const confirmation = container.querySelector<HTMLInputElement>('input[type="checkbox"]');
    expect(confirmation).toBeTruthy();
    await click(confirmation!);

    const confirm = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("确认恢复"));
    expect(confirm).toBeTruthy();
    await click(confirm!);
    const repairCall = calls.find(({ path }) => path.endsWith("/repairs/gateway/confirm"));
    expect(repairCall?.init.method).toBe("POST");
    expect(JSON.parse(String(repairCall?.init.body))).toMatchObject({ action: "restore_last_good", expected_revision: 4, confirmed: true });
    expect((repairCall?.init.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
    await act(async () => root.unmount());
  });

  it("reuses one idempotency key when retrying an uncertain repair response", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch({ failConfirmOnce: true });
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();
    const repair = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("恢复最近可用配置"));
    await click(repair!);
    await click(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
    const confirm = () => [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("确认恢复"))!;

    await click(confirm());
    expect(container.textContent).toContain("network disconnected");
    const first = calls.find(({ path }) => path.endsWith("/confirm"));
    expect(first).toBeTruthy();
    const firstKey = (first!.init.headers as Record<string, string>)["Idempotency-Key"];
    expect(firstKey).toBeTruthy();

    await click(confirm());
    const keys = calls.filter(({ path }) => path.endsWith("/confirm"))
      .map(({ init }) => (init.headers as Record<string, string>)["Idempotency-Key"]);
    expect(keys).toEqual([firstKey, firstKey]);
    await act(async () => root.unmount());
  });

  it("refreshes revision and requires a new confirmation after a conflict", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch({ conflictConfirmOnce: true, connectionRevisions: [4, 5] });
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();
    const openRepair = () => [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("恢复最近可用配置"))!;
    const checkbox = () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    const confirm = () => [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("确认恢复"))!;

    await click(openRepair());
    await click(checkbox());
    await click(confirm());
    expect(container.textContent).toContain("版本已变化");
    expect(container.textContent).toContain("配置版本 5");
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    await click(openRepair());
    await click(checkbox());
    await click(confirm());
    const repairCalls = calls.filter(({ path }) => path.endsWith("/confirm"));
    const bodies = repairCalls.map(({ init }) => JSON.parse(String(init.body)));
    const keys = repairCalls.map(({ init }) => (init.headers as Record<string, string>)["Idempotency-Key"]);
    expect(bodies.map((body) => body.expected_revision)).toEqual([4, 5]);
    expect(keys[0]).not.toBe(keys[1]);
    await act(async () => root.unmount());
  });

  it("does not claim the connection was refreshed when the post-conflict refresh fails", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    setupFetch({ conflictConfirmOnce: true, failConnectionsAfterFirst: true });
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();
    const openRepair = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("恢复最近可用配置"))!;
    await click(openRepair);
    await click(container.querySelector<HTMLInputElement>("input[type=checkbox]")!);
    const confirm = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("确认恢复"))!;
    await click(confirm);
    expect(container.textContent).toContain("无法读取最新连接版本");
    expect(container.textContent).not.toContain("页面已刷新");
    await act(async () => root.unmount());
  });

  it.each([
    [403, { detail: "Platform administrator token is invalid" }, "无权访问"],
    [503, { detail: { code: "AGENTS_UNAVAILABLE" } }, "Agents 服务暂不可用"],
  ])("shows authorization/offline state for status %s", async (status, body, expected) => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    setupFetch({ fail: { status: Number(status), body } });
    const { container, root } = await mount(<MaintenancePage />);
    await flushEffects();
    expect(container.textContent).toContain(expected);
    await act(async () => root.unmount());
  });
});
