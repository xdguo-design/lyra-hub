import { useEffect, useState } from "react";

import {
  agentsLogin,
  agentsLogout,
  checkTenantGatewayConfig,
  checkTenantGatewayDraft,
  createAgentRole,
  createAgentRoleVersion,
  createRegisteredAgent,
  createRegisteredAgentVersion,
  getAgentsIdentity,
  getTenantGatewayConfig,
  listAgentRoleVersions,
  listAgentRoles,
  listGatewayModels,
  listRegisteredAgentVersions,
  listRegisteredAgents,
  publishAgentRoleVersion,
  publishRegisteredAgentVersion,
  runRegisteredAgent,
  saveTenantGatewayConfig,
} from "./api";
import type { AgentRun, AgentsPrincipal, GovernanceRole, RegisteredAgent, TenantGatewayConfig } from "./types";

const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765";

type WorkRolesPageProps = { onOpenGateway?: () => void };

function splitLines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

const AGENTS_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `run-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function WorkRolesPage({ onOpenGateway }: WorkRolesPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [identity, setIdentity] = useState<AgentsPrincipal | null>(null);
  const [gateway, setGateway] = useState<TenantGatewayConfig | null>(null);
  const [gatewayUrl, setGatewayUrl] = useState(DEFAULT_GATEWAY_URL);
  const [gatewayToken, setGatewayToken] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<Record<string, unknown>[]>([]);
  const [modelConnectionHealthy, setModelConnectionHealthy] = useState(false);
  const [roles, setRoles] = useState<GovernanceRole[]>([]);
  const [agents, setAgents] = useState<RegisteredAgent[]>([]);
  const [roleId, setRoleId] = useState("novel-writer");
  const [roleName, setRoleName] = useState("小说创作助手");
  const [responsibilities, setResponsibilities] = useState("根据用户给出的故事设定和任务撰写小说内容");
  const [constraints, setConstraints] = useState("保持人物、时间线和世界观设定一致\n不擅自改变用户已确认的情节");
  const [agentId, setAgentId] = useState("novel-writer-agent");
  const [agentName, setAgentName] = useState("小说创作助手");
  const [task, setTask] = useState("");
  const [result, setResult] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!accessToken) return;
    let active = true;
    void Promise.allSettled([
      getAgentsIdentity(accessToken),
      getTenantGatewayConfig(accessToken),
      listAgentRoles(accessToken),
      listRegisteredAgents(accessToken),
      listGatewayModels(),
    ]).then((values) => {
      if (!active) return;
      const [identityResult, gatewayResult, rolesResult, agentsResult, modelsResult] = values;
      if (identityResult.status === "fulfilled") setIdentity(identityResult.value);
      if (gatewayResult.status === "fulfilled") {
        setGateway(gatewayResult.value);
        if (gatewayResult.value.base_url) setGatewayUrl(gatewayResult.value.base_url);
        if (gatewayResult.value.model) setModel(gatewayResult.value.model);
      }
      if (rolesResult.status === "fulfilled") {
        setRoles(rolesResult.value);
        const selected = rolesResult.value.find((item) => item.current_version) ?? rolesResult.value[0];
        if (selected) setRoleId(selected.id);
      }
      if (agentsResult.status === "fulfilled") {
        setAgents(agentsResult.value);
        const selected = agentsResult.value.find((item) => item.current_version) ?? agentsResult.value[0];
        if (selected) setAgentId(selected.id);
      }
      if (modelsResult.status === "fulfilled") {
        setModels(modelsResult.value);
        if (!model && modelsResult.value.length) {
          setModel(String(modelsResult.value[0].id ?? modelsResult.value[0].name ?? ""));
        }
      }
      const failures = values.filter((item) => item.status === "rejected");
      if (failures.length) setMessage("已登录；部分目录暂不可用，请检查 Gateway / Agents 连接后刷新页面。");
    });
    return () => { active = false; };
  }, [accessToken]);

  async function login() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const session = await agentsLogin(email.trim(), password);
      if (!session.access_token) throw new Error("Agents 登录没有返回访问会话");
      setPassword("");
      setAccessToken(session.access_token);
      setRefreshToken(session.refresh_token ?? "");
      setMessage("Agents 登录成功，正在读取租户模型与角色目录。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agents 登录失败");
    } finally {
      setBusy(false);
    }
  }

  async function connectModel() {
    if (!accessToken || !gatewayToken.trim() || !gatewayUrl.trim() || !model.trim()) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const draft = {
        base_url: gatewayUrl.trim(),
        token: gatewayToken,
        model: model.trim(),
      };
      const check = await checkTenantGatewayDraft(accessToken, draft);
      setModelConnectionHealthy(check.healthy);
      if (!check.healthy) {
        setError(`模型连接检查失败，配置未保存：${check.code}`);
        return;
      }
      const saved = await saveTenantGatewayConfig(accessToken, draft);
      setGateway(saved);
      setGatewayToken("");
      setMessage(`模型连接正常：${saved.model ?? model}`);
    } catch (reason) {
      setModelConnectionHealthy(false);
      setError(reason instanceof Error ? reason.message : "模型连接失败");
    } finally {
      setBusy(false);
    }
  }

  async function checkSavedModel() {
    if (!accessToken || !gateway?.configured) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const check = await checkTenantGatewayConfig(accessToken);
      setModelConnectionHealthy(check.healthy);
      setMessage(check.healthy ? "已保存的模型调用链路正常。" : `模型连接检查失败：${check.code}`);
    } catch (reason) {
      setModelConnectionHealthy(false);
      setError(reason instanceof Error ? reason.message : "模型连接检查失败");
    } finally {
      setBusy(false);
    }
  }

  async function createRole() {
    if (!accessToken || !identity) return;
    if (!AGENTS_ID_PATTERN.test(roleId.trim())) {
      setError("角色 ID 需以字母或数字开头，只能包含字母、数字、下划线和连字符，最多 128 位。");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let role = roles.find((item) => item.id === roleId.trim());
      if (role?.current_version) {
        setRoleId(role.id);
        setMessage(`角色「${role.name}」已发布，可直接绑定 Agent。`);
        return;
      }
      if (!role) {
        role = await createAgentRole(accessToken, {
          id: roleId.trim(),
          name: roleName.trim(),
          owner: identity.id,
          description: "由 Lyra Hub 管理的小说创作工作角色",
        });
        setRoles((current) => [...current.filter((item) => item.id !== role!.id), role!]);
      }
      const versions = await listAgentRoleVersions(accessToken, role.id);
      if (!versions.some((item) => item.version === "1")) {
        await createAgentRoleVersion(accessToken, role.id, {
          version: "1",
          responsibilities: splitLines(responsibilities),
          constraints: splitLines(constraints),
          created_by: identity.id,
        });
      }
      const published = await publishAgentRoleVersion(accessToken, role.id, "1");
      setRoles((current) => [...current.filter((item) => item.id !== published.id), published]);
      setRoleId(published.id);
      setMessage(`角色「${published.name}」v1 已发布，可以绑定到 Agent。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "角色创建或发布失败；可修复问题后重试，已创建的角色会继续使用。");
    } finally {
      setBusy(false);
    }
  }

  async function createAgent() {
    if (!accessToken || !identity) return;
    if (!AGENTS_ID_PATTERN.test(agentId.trim())) {
      setError("Agent ID 需以字母或数字开头，只能包含字母、数字、下划线和连字符，最多 128 位。");
      return;
    }
    const selectedRole = roles.find((item) => item.id === roleId && item.current_version);
    if (!selectedRole) {
      setError("请先创建并发布工作角色，再绑定 Agent。");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let agent = agents.find((item) => item.id === agentId.trim());
      if (agent?.current_version) {
        const publishedAgent = agent;
        const publishedVersions = await listRegisteredAgentVersions(accessToken, publishedAgent.id);
        const publishedDefinition = publishedVersions.find((item) => item.version === publishedAgent.current_version);
        if (publishedDefinition?.role_id !== selectedRole.id) {
          setError(`Agent「${publishedAgent.name}」当前版本绑定的是「${String(publishedDefinition?.role_id ?? "未知角色")}」，无法改绑到「${selectedRole.name}」。请使用新的 Agent ID。`);
          return;
        }
        setAgentId(publishedAgent.id);
        setMessage(`Agent「${publishedAgent.name}」已发布并绑定「${selectedRole.name}」，可直接执行任务。`);
        return;
      }
      if (!agent) {
        agent = await createRegisteredAgent(accessToken, {
          id: agentId.trim(),
          name: agentName.trim(),
          owner: identity.id,
          description: `使用工作角色 ${selectedRole.name} 完成模型任务`,
        });
        setAgents((current) => [...current.filter((item) => item.id !== agent!.id), agent!]);
      }
      const versions = await listRegisteredAgentVersions(accessToken, agent.id);
      const existing = versions.find((item) => item.version === "1");
      if (existing && existing.role_id !== selectedRole.id) {
        throw new Error(`Agent v1 已绑定角色 ${String(existing.role_id ?? "未知")}，请使用新的 Agent ID。`);
      }
      if (!existing) {
        await createRegisteredAgentVersion(accessToken, agent.id, {
          version: "1",
          role_id: selectedRole.id,
          created_by: identity.id,
        });
      }
      const published = await publishRegisteredAgentVersion(accessToken, agent.id, "1");
      setAgents((current) => [...current.filter((item) => item.id !== published.id), published]);
      setAgentId(published.id);
      setMessage(`Agent「${published.name}」v1 已发布并绑定「${selectedRole.name}」。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent 创建或发布失败；可修复问题后重试，已创建的 Agent 会继续使用。");
    } finally {
      setBusy(false);
    }
  }

  async function runTask() {
    if (!accessToken || !task.trim()) return;
    const runnable = agents.find((item) => item.id === agentId && item.current_version);
    if (!runnable || !gateway?.configured || !modelConnectionHealthy) {
      setError("需要先连接并检查模型，再创建并发布绑定角色的 Agent。");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    setResult(null);
    try {
      const response = await runRegisteredAgent(accessToken, runnable.id, task.trim(), idempotencyKey());
      setResult(response.data);
      setMessage(response.data.status === "succeeded" ? "任务执行完成。" : `任务状态：${response.data.status}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "角色任务执行失败");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    let revokeFailed = false;
    if (refreshToken) {
      try {
        await agentsLogout(refreshToken);
      } catch {
        revokeFailed = true;
      }
    }
    setRefreshToken("");
    setAccessToken("");
    setIdentity(null);
    setGateway(null);
    setRoles([]);
    setAgents([]);
    setModelConnectionHealthy(false);
    setResult(null);
    setError(revokeFailed ? "已退出本页面，但 Agents 会话撤销失败；请确认网络后重新登录并退出。" : "");
    setMessage("");
  }

  if (!accessToken) {
    return <section className="section">
      <div className="sectionHead"><div><h3>Agents 登录</h3><p>使用租户管理员账号管理工作角色、模型连接与 Agent 任务。</p></div></div>
      <div className="configCard workRoleLogin">
        <label>邮箱<input aria-label="Agents 邮箱" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label>密码<input aria-label="密码" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <button className="primaryButton" disabled={busy || !email.trim() || !password} onClick={() => void login()}>{busy ? "登录中…" : "登录 Agents"}</button>
        {error && <div className="alert" role="alert">{error}</div>}
      </div>
    </section>;
  }

  const selectedRole = roles.find((item) => item.id === roleId && item.current_version);
  const selectedAgent = agents.find((item) => item.id === agentId && item.current_version);
  const modelNames = models.map((item) => String(item.id ?? item.name ?? "")).filter(Boolean);

  return <section className="section workRolesPage">
    <div className="sectionHead">
      <div><h3>工作角色与任务测试</h3><p>{identity ? `已登录 ${identity.id} · 租户 ${identity.tenant_id ?? "未选择"}` : "Agents 身份已验证"}</p></div>
      <button className="secondaryButton" onClick={() => void logout()}>退出 Agents</button>
    </div>

    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className={modelConnectionHealthy ? "inlineStatus good" : "inlineStatus"} role="status">{message}</div>}

    <div className="workRoleSteps">
      <section className="configCard">
        <div className="configTitle"><strong>1. 模型链接</strong><small>{gateway?.configured ? `已保存 ${gateway.model ?? "模型"}` : "尚未配置租户模型"}</small></div>
        {onOpenGateway && <div className="inlineActions"><span className="helperText">需要添加供应商 API Key 或模型路由时，先到 Gateway 管理页配置。</span><button type="button" className="linkButton" onClick={onOpenGateway}>前往 Gateway 设置</button></div>}
        <label>Gateway 地址<input aria-label="Gateway 地址" value={gatewayUrl} onChange={(event) => setGatewayUrl(event.target.value)} placeholder={DEFAULT_GATEWAY_URL} /></label>
        <label>Gateway 应用令牌<input aria-label="Gateway 应用令牌" type="password" autoComplete="new-password" value={gatewayToken} onChange={(event) => setGatewayToken(event.target.value)} placeholder={gateway?.key_present ? "已保存，输入新值可替换" : "只写入 Agents 加密凭据库"} /></label>
        <label>模型<input aria-label="模型" list="gateway-model-list" value={model} onChange={(event) => setModel(event.target.value)} placeholder="选择或输入 Gateway 模型 ID" /><datalist id="gateway-model-list">{modelNames.map((name) => <option key={name} value={name} />)}</datalist></label>
        <small className="helperText">供应商 API Key 由 Gateway 管理；这里保存 Agents 使用的 Gateway 应用令牌，页面不会回显令牌。</small>
        <div className="inlineActions">
          <button className="secondaryButton" disabled={busy || !gatewayToken.trim() || !gatewayUrl.trim() || !model.trim()} onClick={() => void connectModel()}>{busy ? "处理中…" : "保存并检查模型连接"}</button>
          {gateway?.configured && <button className="secondaryButton" disabled={busy} onClick={() => void checkSavedModel()}>检查已保存模型连接</button>}
        </div>
        <div className={modelConnectionHealthy ? "inlineStatus good" : "inlineStatus"} aria-live="polite">
          {modelConnectionHealthy ? "模型调用链路已检查" : gateway?.configured ? "模型配置已保存；请重新输入应用令牌并检查连接" : "等待配置模型连接"}
        </div>
      </section>

      <section className="configCard">
        <div className="configTitle"><strong>2. 创建工作角色</strong><small>职责和约束会进入 Agent 的实际模型提示词</small></div>
        <label>角色 ID<input aria-label="角色 ID" value={roleId} onChange={(event) => setRoleId(event.target.value)} /></label>
        <label>角色名称<input aria-label="角色名称" value={roleName} onChange={(event) => setRoleName(event.target.value)} /></label>
        <label>职责<textarea aria-label="职责" rows={3} value={responsibilities} onChange={(event) => setResponsibilities(event.target.value)} /></label>
        <label>约束<textarea aria-label="约束" rows={3} value={constraints} onChange={(event) => setConstraints(event.target.value)} /></label>
        <button className="secondaryButton" disabled={busy || !AGENTS_ID_PATTERN.test(roleId.trim()) || !roleName.trim() || !splitLines(responsibilities).length} onClick={() => void createRole()}>{busy ? "处理中…" : "创建并发布角色"}</button>
        {roles.length > 0 && <label>已发布角色<select aria-label="已发布角色" value={roleId} onChange={(event) => setRoleId(event.target.value)}>{roles.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id} · {item.current_version ? `已发布 v${item.current_version}` : "草稿，可继续发布"}</option>)}</select></label>}
        {selectedRole && <div className="inlineStatus good">当前角色：{selectedRole.name} · v{selectedRole.current_version}</div>}
      </section>

      <section className="configCard">
        <div className="configTitle"><strong>3. 绑定并发布 Agent</strong><small>Agent 版本固定引用已发布角色</small></div>
        <label>Agent ID<input aria-label="Agent ID" value={agentId} onChange={(event) => setAgentId(event.target.value)} /></label>
        <label>Agent 名称<input aria-label="Agent 名称" value={agentName} onChange={(event) => setAgentName(event.target.value)} /></label>
        <button className="secondaryButton" disabled={busy || !selectedRole || !AGENTS_ID_PATTERN.test(agentId.trim()) || !agentName.trim()} onClick={() => void createAgent()}>{busy ? "处理中…" : "创建并发布 Agent"}</button>
        {agents.length > 0 && <label>已有 Agent<select aria-label="已有 Agent" value={agentId} onChange={(event) => setAgentId(event.target.value)}>{agents.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id} · {item.current_version ? `已发布 v${item.current_version}` : "草稿，可继续发布"}</option>)}</select></label>}
        {selectedAgent && <div className="inlineStatus good">Agent 已发布：{selectedAgent.name} · v{selectedAgent.current_version}</div>}
      </section>

      <section className="configCard">
        <div className="configTitle"><strong>4. 通过角色执行任务</strong><small>需要有效模型连接；请求带幂等键，防止重复执行</small></div>
        <label>任务内容<textarea aria-label="任务内容" rows={4} maxLength={32768} value={task} onChange={(event) => setTask(event.target.value)} placeholder="例如：写一段悬疑小说开篇，主角在深夜收到十年前自己的来信。" /></label>
        <button className="primaryButton" disabled={busy || !selectedAgent || !modelConnectionHealthy || !task.trim()} onClick={() => void runTask()}>{busy ? "模型执行中…" : "通过角色执行"}</button>
        {result && <article className="workRoleResult" aria-label="任务结果">
          <div><strong>{result.status === "succeeded" ? "执行成功" : `执行状态：${result.status}`}</strong><small>Run {result.run_id} · {result.model ?? model}</small></div>
          {result.output ? <p>{result.output}</p> : result.error ? <p>执行失败：{result.error.code}</p> : <p>暂时没有可展示的输出。</p>}
          {result.usage && <small>Token 用量：{JSON.stringify(result.usage)}</small>}
        </article>}
      </section>
    </div>
  </section>;
}
