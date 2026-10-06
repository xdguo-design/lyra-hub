// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act } from "react";

import { App } from "./App";
import { click, flushEffects, mount } from "./test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

it("opens maintenance and Agents tenants from Hub navigation", async () => {
  sessionStorage.setItem("lyra-hub-admin-token", "hub-admin-secret");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).replace("http://localhost:8000", "");
    if (path === "/health") return new Response(JSON.stringify({ status: "ok" }));
    if (path === "/api/v1/applications" || path === "/api/v1/navigation") return new Response("[]");
    if (path === "/api/v1/platform/status") return new Response(JSON.stringify({ services: [] }));
    if (path === "/api/v1/maintenance/overview") return new Response(JSON.stringify({ data: { services: {}, open_alerts: 0, agents_available: null } }));
    if (path.startsWith("/api/v1/maintenance/alerts?")) return new Response(JSON.stringify({ data: [] }));
    if (path === "/api/v1/platform/connections") return new Response(JSON.stringify({ data: [] }));
    if (path.startsWith("/api/v1/agents/platform/tenants?")) return new Response(JSON.stringify({ items: [] }));
    return new Response("{}", { status: 404 });
  }));
  const { container, root } = await mount(<App />);
  await flushEffects();

  const maintenance = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("平台维护"));
  await click(maintenance!);
  expect(container.querySelector("h2")?.textContent).toBe("平台维护");

  const tenants = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Agents 租户"));
  await click(tenants!);
  expect(container.querySelector("h2")?.textContent).toBe("Agents 租户");

  const roles = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("工作角色与任务"));
  await click(roles!);
  expect(container.querySelector("h1")?.textContent).toBe("工作角色与任务");
  expect(container.textContent).toContain("Agents 登录");
  await act(async () => root.unmount());
});
