// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { WorkRolesPage } from "./WorkRolesPage";
import { click, flushEffects, mount } from "./test-utils";

function setupFetch(options: { configured?: boolean; draftHealthy?: boolean; failRoleVersionOnce?: boolean; failAgentVersionOnce?: boolean } = {}) {
  let roleVersionFailures = options.failRoleVersionOnce ? 1 : 0;
  let agentVersionFailures = options.failAgentVersionOnce ? 1 : 0;
  const calls: Array<{ path: string; init: RequestInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input).replace("http://localhost:8000", "");
    calls.push({ path, init });
    const method = init.method ?? "GET";
    let body: unknown = {};
    if (typeof init.body === "string") body = JSON.parse(init.body);
    const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
      status,
      headers: { "Content-Type": "application/json" },
    });

    if (path === "/api/v1/agents/auth/login" && method === "POST") {
      return response({ access_token: "session-access", refresh_token: "session-refresh", expires_in: 900 });
    }
    if (path === "/api/v1/agents/auth/me") {
      return response({ id: "user-1", tenant_id: "tenant-a", role: "tenant_admin" });
    }
    if (path === "/api/v1/agents/tenants/me/gateway" && method === "GET") {
      return response(options.configured
        ? { configured: true, key_present: true, base_url: "http://127.0.0.1:8765", model: "agnes-3.0-flash" }
        : { configured: false, key_present: false, base_url: null, model: null });
    }
    if (path === "/api/v1/agents/tenants/me/gateway" && method === "PUT") {
      return response({ configured: true, key_present: true, base_url: (body as { base_url: string }).base_url, model: (body as { model: string }).model });
    }
    if (path === "/api/v1/agents/tenants/me/gateway/check") return response({ healthy: true, code: "gateway_reachable" });
    if (path === "/api/v1/agents/tenants/me/gateway/check-draft" && method === "POST") {
      return response({ healthy: options.draftHealthy ?? true, code: options.draftHealthy === false ? "gateway_model_not_found" : "gateway_reachable" });
    }
    if (path === "/api/v1/capabilities/model.list/invoke") return response({ result: { data: [{ id: "agnes-3.0-flash" }] } });
    if (path === "/api/v1/agents/roles" && method === "GET") return response({ items: [], total: 0 });
    if (path === "/api/v1/agents/agents" && method === "GET") return response({ items: [], total: 0 });
    if (path === "/api/v1/agents/roles" && method === "POST") return response({ id: "novel-writer", name: "小说创作助手" }, 201);
    if (path === "/api/v1/agents/roles/novel-writer/versions" && method === "GET") return response([]);
    if (path === "/api/v1/agents/roles/novel-writer/versions" && method === "POST") {
      if (roleVersionFailures > 0) { roleVersionFailures -= 1; return response({ detail: "temporary failure" }, 503); }
      return response({ role_id: "novel-writer", version: "1" }, 201);
    }
    if (path === "/api/v1/agents/roles/novel-writer/current-version" && method === "PUT") return response({ id: "novel-writer", current_version: "1" });
    if (path === "/api/v1/agents/agents" && method === "POST") return response({ id: "novel-writer-agent", name: "小说创作助手" }, 201);
    if (path === "/api/v1/agents/agents/novel-writer-agent/versions" && method === "GET") return response([]);
    if (path === "/api/v1/agents/agents/novel-writer-agent/versions" && method === "POST") {
      if (agentVersionFailures > 0) { agentVersionFailures -= 1; return response({ detail: "temporary failure" }, 503); }
      return response({ agent_id: "novel-writer-agent", version: "1" }, 201);
    }
    if (path === "/api/v1/agents/agents/novel-writer-agent/current-version" && method === "PUT") return response({ id: "novel-writer-agent", current_version: "1" });
    if (path === "/api/v1/agents/agents/novel-writer-agent/runs" && method === "POST") {
      return response({ data: { run_id: "run-1", status: "succeeded", output: "雾从旧站台漫上来，最后一班列车没有乘客。", model: "agnes-3.0-flash" } }, 201);
    }
    return response({ detail: `Unhandled ${method} ${path}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

async function fillInput(container: HTMLElement, label: string, value: string) {
  let input: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | undefined;
  for (let attempt = 0; attempt < 20 && !input; attempt += 1) {
    input = Array.from(container.querySelectorAll("input, textarea, select"))
      .find((element) => element.getAttribute("aria-label") === label) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | undefined;
    if (!input) await flushEffects();
  }
  if (!input) throw new Error(`Missing field ${label}`);
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
  await flushEffects();
}

async function clickNamed(container: HTMLElement, label: string) {
  let button: HTMLButtonElement | undefined;
  for (let attempt = 0; attempt < 20 && !button; attempt += 1) {
    button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.trim() === label);
    if (!button) await flushEffects();
  }
  if (!button) throw new Error(`Missing button ${label}`);
  await click(button);
}

describe("WorkRolesPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows Agents login before loading or mutating tenant role data", async () => {
    const calls = setupFetch();
    const { container, root } = await mount(<WorkRolesPage />);

    expect(container.textContent).toContain("Agents 登录");
    expect(container.querySelector('[aria-label="Agents 邮箱"]')).not.toBeNull();
    expect(calls).toHaveLength(0);
    await root.unmount();
  });

  it("connects a tenant model and runs a task through a published role-bound Agent", async () => {
    const calls = setupFetch();
    const { container, root } = await mount(<WorkRolesPage />);

    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await fillInput(container, "Gateway 地址", "http://127.0.0.1:8765");
    await fillInput(container, "Gateway 应用令牌", "gateway-app-token");
    await fillInput(container, "模型", "agnes-3.0-flash");
    await clickNamed(container, "保存并检查模型连接");
    await fillInput(container, "角色 ID", "novel-writer");
    await fillInput(container, "角色名称", "小说创作助手");
    await fillInput(container, "职责", "根据设定撰写小说章节");
    await fillInput(container, "约束", "保持人物和世界观一致");
    await clickNamed(container, "创建并发布角色");
    await fillInput(container, "Agent ID", "novel-writer-agent");
    await fillInput(container, "Agent 名称", "小说创作助手");
    await clickNamed(container, "创建并发布 Agent");
    await fillInput(container, "任务内容", "写一段悬疑小说开篇");
    await clickNamed(container, "通过角色执行");

    expect(container.textContent).toContain("雾从旧站台漫上来");
    expect(calls.map(({ path }) => path)).toContain("/api/v1/agents/roles/novel-writer/current-version");
    expect(calls.map(({ path }) => path)).toContain("/api/v1/agents/agents/novel-writer-agent/runs");
    const runCall = calls.find(({ path }) => path.endsWith("/agents/novel-writer-agent/runs"));
    expect(runCall?.init.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
    expect(runCall?.init.headers).toMatchObject({ Authorization: "Bearer session-access" });
    await root.unmount();
  });


  it("does not overwrite saved settings when draft model validation fails", async () => {
    const calls = setupFetch({ draftHealthy: false });
    const { container, root } = await mount(<WorkRolesPage />);
    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await fillInput(container, "Gateway 地址", "http://127.0.0.1:8765");
    await fillInput(container, "Gateway 应用令牌", "bad-gateway-token");
    await fillInput(container, "模型", "missing-model");
    await clickNamed(container, "保存并检查模型连接");

    expect(container.textContent).toContain("gateway_model_not_found");
    expect(calls.some(({ path, init }) => path === "/api/v1/agents/tenants/me/gateway" && init.method === "PUT")).toBe(false);
    await root.unmount();
  });

  it("resumes role publication after a version creation failure without recreating the role", async () => {
    const calls = setupFetch({ failRoleVersionOnce: true });
    const { container, root } = await mount(<WorkRolesPage />);
    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await fillInput(container, "角色 ID", "novel-writer");
    await clickNamed(container, "创建并发布角色");
    await clickNamed(container, "创建并发布角色");

    expect(calls.filter(({ path, init }) => path === "/api/v1/agents/roles" && init.method === "POST")).toHaveLength(1);
    expect(calls.some(({ path, init }) => path === "/api/v1/agents/roles/novel-writer/current-version" && init.method === "PUT")).toBe(true);
    await root.unmount();
  });


  it("resumes Agent publication after version creation fails without recreating the Agent", async () => {
    const calls = setupFetch({ failAgentVersionOnce: true });
    const { container, root } = await mount(<WorkRolesPage />);
    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await clickNamed(container, "创建并发布角色");
    await fillInput(container, "Agent ID", "novel-writer-agent");
    await clickNamed(container, "创建并发布 Agent");
    await clickNamed(container, "创建并发布 Agent");

    expect(calls.filter(({ path, init }) => path === "/api/v1/agents/agents" && init.method === "POST")).toHaveLength(1);
    expect(calls.some(({ path, init }) => path === "/api/v1/agents/agents/novel-writer-agent/current-version" && init.method === "PUT")).toBe(true);
    await root.unmount();
  });

  it("rejects role IDs outside the Agents path identifier format before creating anything", async () => {
    const calls = setupFetch();
    const { container, root } = await mount(<WorkRolesPage />);
    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await fillInput(container, "角色 ID", "bad/id");
    const button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.trim() === "创建并发布角色");
    expect(button?.hasAttribute("disabled")).toBe(true);
    expect(calls.some(({ path, init }) => path === "/api/v1/agents/roles" && init.method === "POST")).toBe(false);
    await root.unmount();
  });

  it("revokes the Agents refresh session when logging out", async () => {
    const calls = setupFetch();
    const { container, root } = await mount(<WorkRolesPage />);
    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await clickNamed(container, "退出 Agents");

    const logout = calls.find(({ path, init }) => path === "/api/v1/agents/auth/logout");
    expect(logout?.init.method).toBe("POST");
    expect(JSON.parse(String(logout?.init.body))).toEqual({ refresh_token: "session-refresh" });
    expect(container.textContent).toContain("Agents 登录");
    await root.unmount();
  });

  it("checks an already saved model connection without asking for its token again", async () => {
    const calls = setupFetch({ configured: true });
    const { container, root } = await mount(<WorkRolesPage />);
    await fillInput(container, "Agents 邮箱", "writer@example.test");
    await fillInput(container, "密码", "test-password");
    await clickNamed(container, "登录 Agents");
    await clickNamed(container, "检查已保存模型连接");

    expect(container.textContent).toContain("模型调用链路已检查");
    expect(calls.some(({ path, init }) => path === "/api/v1/agents/tenants/me/gateway" && init.method === "PUT")).toBe(false);
    await root.unmount();
  });
});

