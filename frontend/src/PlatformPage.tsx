import { useCallback, useEffect, useState } from "react";

import {
  checkPlatformConnection,
  clearSavedPlatformConnection,
  invokeCapability,
  listPlatformConnections,
  restorePlatformConnection,
  savePlatformConnection,
  type PlatformConnection,
  type PlatformConnectionCheck,
} from "./api";

type PlatformPageProps = { service: PlatformConnection["service_id"] };

export function PlatformPage({ service }: PlatformPageProps) {
  const gateway = service === "gateway";
  const [connection, setConnection] = useState<PlatformConnection | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [credential, setCredential] = useState("");
  const [clearCredential, setClearCredential] = useState(false);
  const [adminToken, setAdminToken] = useState(() => sessionStorage.getItem("lyra-hub-admin-token") ?? "");
  const [check, setCheck] = useState<PlatformConnectionCheck | null>(null);
  const [catalog, setCatalog] = useState<Record<string, unknown>[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [generation, setGeneration] = useState("");
  const [busy, setBusy] = useState(false);
  const [pageError, setPageError] = useState("");

  const refreshConnection = useCallback(async () => {
    const items = await listPlatformConnections();
    const item = items.find((value) => value.service_id === service) ?? null;
    setConnection(item);
    if (item) setBaseUrl(item.base_url);
  }, [service]);

  const refreshCatalog = useCallback(async () => {
    setCatalogError("");
    try {
      const result = await invokeCapability(gateway ? "model.list" : "agent.list");
      const entries = gateway ? result.data : result.items;
      setCatalog(Array.isArray(entries) ? entries as Record<string, unknown>[] : []);
    } catch (reason) {
      setCatalog([]);
      setCatalogError(reason instanceof Error ? reason.message : "目录读取失败");
    }
  }, [gateway]);

  useEffect(() => {
    void Promise.all([refreshConnection(), refreshCatalog()]).catch((reason: unknown) => {
      setPageError(reason instanceof Error ? reason.message : "页面加载失败");
    });
  }, [refreshConnection, refreshCatalog]);

  function authDraft() {
    if (!connection) throw new Error("连接配置仍在加载");
    return {
      base_url: baseUrl,
      ...(credential ? { credential } : {}),
      ...(clearCredential ? { clear_credential: true } : {}),
      expected_revision: connection.revision,
    };
  }

  async function runCheck(save: boolean) {
    setPageError("");
    setBusy(true);
    try {
      const result = save
        ? (await savePlatformConnection(service, authDraft())).check
        : await checkPlatformConnection(service, authDraft());
      setCheck(result);
      setCredential("");
      setClearCredential(false);
      if (save) await refreshConnection();
      if (result.catalog_access) await refreshCatalog();
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "连接检查失败");
    } finally {
      setBusy(false);
    }
  }

  async function restore() {
    if (!connection) return;
    setBusy(true);
    setPageError("");
    try {
      await restorePlatformConnection(service, connection.revision);
      setCheck(null);
      await Promise.all([refreshConnection(), refreshCatalog()]);
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "恢复失败");
    } finally {
      setBusy(false);
    }
  }

  async function clearSaved() {
    if (!connection) return;
    setBusy(true);
    setPageError("");
    try {
      await clearSavedPlatformConnection(service, connection.revision);
      setCheck(null);
      await Promise.all([refreshConnection(), refreshCatalog()]);
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "清除保存配置失败");
    } finally {
      setBusy(false);
    }
  }

  async function testGeneration() {
    if (!prompt.trim()) return;
    setBusy(true);
    setGeneration("");
    setPageError("");
    try {
      const result = await invokeCapability("model.generate", { prompt: prompt.trim(), stream: false }, true);
      setGeneration(JSON.stringify(result, null, 2));
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "生成检查失败");
    } finally {
      setBusy(false);
    }
  }

  const label = gateway ? "Gateway" : "Agents";
  const catalogLabel = gateway ? "模型" : "Agent";
  const adminConsoleUrl = gateway && connection
    ? new URL("/admin/", connection.base_url).toString()
    : null;

  return (
    <section className="section">
      <div className="sectionHead">
        <div>
          <h3>{label} 连接与目录</h3>
          <p>{gateway ? "模型目录由 Gateway 管理；Hub 只负责连接、发现和显式生成检查。" : "Agent 定义与版本由 Agent OS 管理；Hub 仅展示其注册表数据。"}</p>
        </div>
        <div className="inlineActions">
          {adminConsoleUrl && <a className="secondaryButton" href={adminConsoleUrl} target="_blank" rel="noreferrer">Gateway 管理供应商与模型</a>}
          <button className="secondaryButton" disabled={busy} onClick={() => void refreshCatalog()}>刷新目录</button>
        </div>
      </div>

      <div className="configCard platformConfig">
        <div className="configTitle">
          <strong>服务连接</strong>
          <small>{connection?.source === "database" ? "Hub 已保存" : "来自环境配置"} · 修订 {connection?.revision ?? "—"}</small>
        </div>
        <label>服务地址<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://service.example" /></label>
        <label>管理令牌<input value={adminToken} onChange={(event) => setAdminToken(event.target.value)} type="password" placeholder="仅保存在当前浏览器会话" /></label>
        <div className="inlineActions">
          <button className="secondaryButton" onClick={() => {
            if (adminToken) sessionStorage.setItem("lyra-hub-admin-token", adminToken);
            else sessionStorage.removeItem("lyra-hub-admin-token");
          }}>保存管理令牌到本会话</button>
          <span>{connection?.credential_configured ? "上游凭据已配置（值不可读取）" : "未配置上游凭据"}</span>
        </div>
        <label>上游访问凭据<input value={credential} onChange={(event) => setCredential(event.target.value)} type="password" placeholder="留空表示沿用已保存凭据" autoComplete="new-password" /></label>
        <label className="checkboxLabel"><input type="checkbox" checked={clearCredential} onChange={(event) => setClearCredential(event.target.checked)} />明确移除已保存凭据</label>
        <div className="inlineActions">
          <button className="secondaryButton" disabled={busy || !connection} onClick={() => void runCheck(false)}>检查草稿连接</button>
          <button className="primaryButton" disabled={busy || !connection} onClick={() => void runCheck(true)}>保存并应用</button>
          <button className="secondaryButton" disabled={busy || !connection?.has_last_good} onClick={() => void restore()}>恢复最近可用配置</button>
          <button className="secondaryButton" disabled={busy || connection?.source !== "database"} onClick={() => void clearSaved()}>清除保存配置并恢复环境值</button>
        </div>
        {check && <div className={check.catalog_access ? "inlineStatus good" : "inlineStatus bad"}>
          {check.catalog_access
            ? `服务可达 · ${check.catalog_count === 0 ? "目录为空" : `${check.catalog_count} 个${catalogLabel}`} · ${new Date(check.checked_at).toLocaleString()}`
            : `${check.error_code ?? "CHECK_FAILED"}${check.detail ? ` · ${typeof check.detail === "string" ? check.detail : JSON.stringify(check.detail)}` : ""}`}
        </div>}
        {connection?.checked_at && <small>最近检查：{new Date(connection.checked_at).toLocaleString()}</small>}
      </div>

      {pageError && <div className="alert">{pageError}</div>}
      <div className="sectionHead platformCatalogHead">
        <div><h3>{catalogLabel}目录</h3><p>{catalogError ? `目录访问失败：${catalogError}` : catalog.length ? `当前发现 ${catalog.length} 个${catalogLabel}` : `目录有效但为空，或尚未刷新。`}</p></div>
      </div>
      {catalogError ? <div className="emptyState">{catalogError}</div> : catalog.length === 0 ? <div className="emptyState">没有可显示的{catalogLabel}。</div> : (
        <div className="platformCatalog">
          {catalog.map((item, index) => <article className="platformCatalogItem" key={String(item.id ?? item.name ?? index)}>
            <strong>{String(item.id ?? item.name ?? `${catalogLabel} ${index + 1}`)}</strong>
            <small>{String(item.name ?? item.description ?? item.owned_by ?? "")}</small>
            {item.enabled === false && <span className="pill badPill">已停用</span>}
          </article>)}
        </div>
      )}

      {gateway && <div className="configCard generationCheck">
        <div className="configTitle"><strong>显式生成检查</strong><small>请求会消耗 Gateway 配额，可能产生费用；不会自动重试。</small></div>
        <label>测试输入<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={2000} rows={3} placeholder="输入一段简短测试内容" /></label>
        <button className="primaryButton" disabled={busy || !prompt.trim()} onClick={() => void testGeneration()}>发起生成检查</button>
        {generation && <pre className="resultPanel">{generation}</pre>}
      </div>}
      {!gateway && <div className="inlineStatus">Agent 执行与 Workflow 执行尚无受支持的外部运行契约，Hub 不会显示或调用执行操作。</div>}
    </section>
  );
}
