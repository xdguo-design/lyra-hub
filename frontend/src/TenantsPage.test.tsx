// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { TenantsPage } from "./TenantsPage";
import { click, flushEffects, mount } from "./test-utils";

const tenant = { id: "tenant-a", name: "Tenant A", active: true, created_at: "2026-10-03T10:00:00Z" };

function setupFetch(options?: { fail?: { status: number; body: unknown }; items?: unknown[] }) {
  const calls: Array<{ path: string; init: RequestInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input).replace("http://localhost:8000", "");
    calls.push({ path, init });
    if (options?.fail) {
      return new Response(JSON.stringify(options.fail.body), {
        status: options.fail.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (path.startsWith("/api/v1/agents/platform/tenants?") || path === "/api/v1/agents/platform/tenants") {
      return new Response(JSON.stringify({ items: options?.items ?? [tenant] }));
    }
    if (path.endsWith("/admins")) return new Response(JSON.stringify({ invitation_token: "invite-once", expires_in: 86400 }), { status: 201 });
    if (init.method === "POST" || init.method === "PATCH") {
      return new Response(JSON.stringify({ ...tenant, active: JSON.parse(String(init.body)).active ?? true }), { status: 201 });
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

describe("TenantsPage", () => {
  it("loads a bounded page with the Hub admin token and performs no writes on entry", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch();
    const { container, root } = await mount(<TenantsPage />);
    await flushEffects();

    expect(container.textContent).toContain("Tenant A");
    expect(calls[0].path).toBe("/api/v1/agents/platform/tenants?limit=50&offset=0");
    expect((calls[0].init.headers as Record<string, string>)["X-Lyra-Admin-Token"]).toBe("hub-admin-secret");
    expect(calls.every(({ init }) => !init.method || init.method === "GET")).toBe(true);
    expect(container.textContent).not.toContain("service credential");
    expect(container.textContent).not.toContain("agent_os_token");
    await act(async () => root.unmount());
  });

  it("creates a tenant, toggles its active state, and reveals an invitation only once", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    const calls = setupFetch();
    const { container, root } = await mount(<TenantsPage />);
    await flushEffects();

    const id = container.querySelector<HTMLInputElement>('[name="tenantId"]')!;
    const name = container.querySelector<HTMLInputElement>('[name="tenantName"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(id, "tenant-b");
      id.dispatchEvent(new Event("input", { bubbles: true }));
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(name, "Tenant B");
      name.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const create = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("创建租户"));
    await click(create!);
    const createCall = calls.find(({ path, init }) => path === "/api/v1/agents/platform/tenants" && init.method === "POST");
    expect(JSON.parse(String(createCall?.init.body))).toEqual({ id: "tenant-b", name: "Tenant B" });

    const toggle = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("停用"));
    expect(toggle).toBeTruthy();
    await click(toggle!);
    expect(calls.some(({ path, init }) => path.endsWith("/platform/tenants/tenant-a") && init.method === "PATCH")).toBe(true);

    const invite = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("邀请管理员"));
    await click(invite!);
    const email = container.querySelector<HTMLInputElement>('[name="adminEmail"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(email, "admin@example.test");
      email.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const submitInvite = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("发送邀请"));
    await click(submitInvite!);
    expect(container.textContent).toContain("invite-once");
    expect(calls.some(({ path, init }) => path.endsWith("/platform/tenants/tenant-a/admins") && init.method === "POST")).toBe(true);
    await act(async () => root.unmount());
  });

  it("shows empty and authorization/offline states", async () => {
    sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
    setupFetch({ items: [] });
    const empty = await mount(<TenantsPage />);
    await flushEffects();
    expect(empty.container.textContent).toContain("暂无租户");
    await act(async () => empty.root.unmount());

    setupFetch({ fail: { status: 403, body: { detail: "Platform administrator token is invalid" } } });
    const denied = await mount(<TenantsPage />);
    await flushEffects();
    expect(denied.container.textContent).toContain("无权访问");
    await act(async () => denied.root.unmount());

    setupFetch({ fail: { status: 503, body: { detail: { code: "AGENTS_UNAVAILABLE" } } } });
    const offline = await mount(<TenantsPage />);
    await flushEffects();
    expect(offline.container.textContent).toContain("Agents 服务暂不可用");
    await act(async () => offline.root.unmount());
  });
});
