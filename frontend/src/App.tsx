import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AppstoreOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  SettingOutlined,
} from "@ant-design/icons";

import {
  getApplication,
  getHubHealth,
  launchApplication,
  listApplications,
  listAuditEvents,
  setApplicationEnabled,
} from "./api";
import type { ApplicationDetail, ApplicationSummary, AuditEvent } from "./types";

type View = "overview" | "applications" | "application" | "operations";

export function App() {
  const [view, setView] = useState<View>("overview");
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [selected, setSelected] = useState<ApplicationDetail | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [hubHealthy, setHubHealthy] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [busyApp, setBusyApp] = useState<string | null>(null);

  const refreshApplications = useCallback(async () => {
    const apps = await listApplications();
    setApplications(apps);
    return apps;
  }, []);

  useEffect(() => {
    void Promise.all([refreshApplications(), getHubHealth()])
      .then(([, healthy]) => setHubHealthy(healthy))
      .catch((reason: unknown) => {
        setHubHealthy(false);
        setError(reason instanceof Error ? reason.message : "加载失败");
      });
  }, [refreshApplications]);

  const categories = useMemo(() => new Set(applications.map((app) => app.category)).size, [applications]);
  const enabledCount = useMemo(() => applications.filter((app) => app.enabled).length, [applications]);

  async function openDetail(appId: string) {
    setError("");
    try {
      setSelected(await getApplication(appId));
      setView("application");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "应用详情加载失败");
    }
  }

  async function toggleEnabled(app: ApplicationSummary | ApplicationDetail) {
    setBusyApp(app.id);
    setError("");
    try {
      const detail = await setApplicationEnabled(app.id, !app.enabled);
      setSelected((current) => (current?.id === detail.id ? detail : current));
      await refreshApplications();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态更新失败");
    } finally {
      setBusyApp(null);
    }
  }

  async function launch(appId: string) {
    setBusyApp(appId);
    setError("");
    try {
      const launchInfo = await launchApplication(appId);
      window.open(launchInfo.url, "_blank", "noopener,noreferrer");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "应用启动失败");
    } finally {
      setBusyApp(null);
    }
  }

  async function openOperations() {
    setError("");
    try {
      setAuditEvents(await listAuditEvents());
      setView("operations");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审计日志加载失败");
    }
  }

  const pageTitle =
    view === "overview"
      ? "AI 应用中枢"
      : view === "applications"
        ? "应用中心"
        : view === "application"
          ? selected?.name ?? "应用详情"
          : "运行与审计";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">L</span><span>Lyra Hub</span></div>
        <div className="eyebrow">WORKSPACE</div>
        <nav>
          <button className={view === "overview" ? "navItem active" : "navItem"} onClick={() => setView("overview")}>
            <DashboardOutlined /> 总览
          </button>
          <button className={view === "applications" || view === "application" ? "navItem active" : "navItem"} onClick={() => setView("applications")}>
            <AppstoreOutlined /> 应用中心
          </button>
          <button className={view === "operations" ? "navItem active" : "navItem"} onClick={() => void openOperations()}>
            <DeploymentUnitOutlined /> 运行与审计
          </button>
          <button className="navItem disabled"><SettingOutlined /> 设置 <span>后续</span></button>
        </nav>
        <div className="sidebarFoot">v0.1 · dev</div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <div className="eyebrow">AI APPLICATION HUB</div>
            <h1>{pageTitle}</h1>
          </div>
          <div className={hubHealthy ? "health good" : "health warning"}>
            <span className="dot" />
            {hubHealthy === null ? "检查中" : hubHealthy ? "Hub API 正常" : "Hub API 未连接"}
          </div>
        </header>

        {error && <div className="alert">{error}</div>}

        {view === "overview" && (
          <>
            <section className="hero">
              <div>
                <div className="eyebrow light">UNIFIED WORKSPACE</div>
                <h2>应用独立运行，能力统一接入</h2>
                <p>Lyra Hub 管应用入口、配置和平台能力；Gateway 管模型，Agent OS 管智能执行。</p>
              </div>
              <div className="heroStats">
                <Stat value={applications.length} label="已注册应用" />
                <Stat value={enabledCount} label="已启用" />
                <Stat value={categories} label="应用分类" />
              </div>
            </section>

            <section className="section">
              <div className="sectionHead">
                <div><h3>我的应用</h3><p>Manifest 注册结果与 Hub 启停状态</p></div>
                <button className="linkButton" onClick={() => setView("applications")}>管理全部应用 →</button>
              </div>
              <div className="appGrid">
                {applications.map((app) => (
                  <ApplicationCard
                    key={app.id}
                    app={app}
                    busy={busyApp === app.id}
                    onManage={() => void openDetail(app.id)}
                    onLaunch={() => void launch(app.id)}
                  />
                ))}
              </div>
            </section>

            <section className="statusGrid">
              <StatusCard title="Gateway" status="待接入" description="模型、Provider、路由、配额和用量" />
              <StatusCard title="Agent OS" status="待接入" description="Agent、Skill、Tool、Workflow 与运行治理" />
              <StatusCard title="Hub Registry" status={applications.length ? "正常" : "待启动"} description="Manifest 校验、持久化状态与应用发现" />
            </section>
          </>
        )}

        {view === "applications" && (
          <section className="section">
            <div className="sectionHead">
              <div><h3>已注册应用</h3><p>应用启停由 Hub 持久化，不修改业务应用源码。</p></div>
            </div>
            <div className="table">
              <div className="tableRow tableHead"><span>应用</span><span>类型</span><span>版本</span><span>接入模式</span><span>状态</span><span>操作</span></div>
              {applications.map((app) => (
                <div className="tableRow" key={app.id}>
                  <span><strong>{app.name}</strong><small>{app.id}</small></span>
                  <span>{app.category}</span>
                  <span>{app.version}</span>
                  <span>{app.integration_type}</span>
                  <span className={app.enabled ? "statusText" : "statusText disabledText"}>{app.enabled ? "● 已启用" : "● 已停用"}</span>
                  <span className="rowActions">
                    <button className="textAction" onClick={() => void openDetail(app.id)}>管理</button>
                    <button className="textAction" disabled={!app.enabled || busyApp === app.id} onClick={() => void launch(app.id)}>打开</button>
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {view === "application" && selected && (
          <section className="detailLayout">
            <article className="section detailMain">
              <div className="detailHeader">
                <div className="appIcon large">{selected.name.slice(0, 1)}</div>
                <div>
                  <div className="eyebrow">{selected.category.toUpperCase()}</div>
                  <h2>{selected.name}</h2>
                  <p>{selected.description}</p>
                </div>
                <span className={selected.enabled ? "pill goodPill" : "pill"}>{selected.enabled ? "已启用" : "已停用"}</span>
              </div>

              <div className="detailActions">
                <button className="primaryButton" disabled={!selected.enabled || busyApp === selected.id} onClick={() => void launch(selected.id)}>从 Hub 打开</button>
                <button className={selected.enabled ? "dangerButton" : "secondaryButton"} disabled={busyApp === selected.id} onClick={() => void toggleEnabled(selected)}>
                  {selected.enabled ? "停用应用" : "启用应用"}
                </button>
              </div>

              <div className="infoGrid">
                <Info label="版本" value={selected.version} />
                <Info label="接入模式" value={selected.integration_type} />
                <Info label="Workspace 路径" value={selected.workspace_path} />
                <Info label="独立入口" value={selected.standalone_url} />
              </div>

              <h3 className="subheading">消费的平台能力</h3>
              <div className="tagList">
                {selected.capabilities_consumed.map((capability) => <span key={capability}>{capability}</span>)}
              </div>

              <h3 className="subheading">权限声明</h3>
              <div className="tagList">
                {selected.permissions.map((permission) => <span key={permission}>{permission}</span>)}
              </div>
            </article>

            <aside className="section detailAside">
              <div className="eyebrow">RUNTIME POLICY</div>
              <h3>Hub 管理状态</h3>
              <p>停用只影响 Hub 内的发现与启动，不破坏应用自己的独立运行能力。</p>
              <div className="policyLine"><span>Manifest</span><strong>v1 / 已验证</strong></div>
              <div className="policyLine"><span>独立运行</span><strong>保留</strong></div>
              <div className="policyLine"><span>Hub 启动</span><strong>{selected.enabled ? "允许" : "禁止"}</strong></div>
            </aside>
          </section>
        )}

        {view === "operations" && (
          <section className="section">
            <div className="sectionHead"><div><h3>配置审计</h3><p>当前记录应用启用/停用等 Hub 配置变更。</p></div></div>
            {auditEvents.length === 0 ? (
              <div className="emptyState">还没有配置变更记录。</div>
            ) : (
              <div className="auditList">
                {auditEvents.map((event) => (
                  <div className="auditRow" key={event.id}>
                    <span className="auditIcon">↳</span>
                    <div><strong>{event.action}</strong><small>{event.target_type} · {event.target_id}</small></div>
                    <time>{new Date(event.created_at).toLocaleString()}</time>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return <div className="stat"><strong>{value}</strong><span>{label}</span></div>;
}

function ApplicationCard({
  app,
  busy,
  onManage,
  onLaunch,
}: {
  app: ApplicationSummary;
  busy: boolean;
  onManage: () => void;
  onLaunch: () => void;
}) {
  return (
    <article className={app.enabled ? "appCard" : "appCard appCardDisabled"}>
      <div className="appIcon">{app.name.slice(0, 1)}</div>
      <div className="appInfo">
        <div className="appTitle"><h4>{app.name}</h4><span>v{app.version}</span></div>
        <p>{app.description || "独立业务 AI 应用"}</p>
        <div className="meta"><span>{app.category}</span><span>{app.integration_type}</span><span className={app.enabled ? "statusText" : "disabledText"}>{app.enabled ? "● 已启用" : "● 已停用"}</span></div>
        <div className="cardActions">
          <button className="textAction" onClick={onManage}>管理</button>
          <button className="textAction" disabled={!app.enabled || busy} onClick={onLaunch}>打开</button>
        </div>
      </div>
    </article>
  );
}

function StatusCard({ title, status, description }: { title: string; status: string; description: string }) {
  const good = status === "正常";
  return <article className="statusCard"><div><span className="eyebrow">{title}</span><h4>{description}</h4></div><span className={good ? "pill goodPill" : "pill"}>{status}</span></article>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="infoItem"><span>{label}</span><strong>{value}</strong></div>;
}
