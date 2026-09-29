import { useEffect, useMemo, useState } from "react";
import { AppstoreOutlined, DashboardOutlined, DeploymentUnitOutlined, SettingOutlined } from "@ant-design/icons";
import { getHubHealth, listApplications } from "./api";
import type { ApplicationSummary } from "./types";

type View = "overview" | "applications";

export function App() {
  const [view, setView] = useState<View>("overview");
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [hubHealthy, setHubHealthy] = useState<boolean | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void Promise.all([listApplications(), getHubHealth()])
      .then(([apps, healthy]) => {
        setApplications(apps);
        setHubHealthy(healthy);
      })
      .catch((reason: unknown) => {
        setHubHealthy(false);
        setError(reason instanceof Error ? reason.message : "加载失败");
      });
  }, []);

  const categories = useMemo(() => new Set(applications.map((app) => app.category)).size, [applications]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">L</span><span>Lyra Hub</span></div>
        <div className="eyebrow">WORKSPACE</div>
        <nav>
          <button className={view === "overview" ? "navItem active" : "navItem"} onClick={() => setView("overview")}>
            <DashboardOutlined /> 总览
          </button>
          <button className={view === "applications" ? "navItem active" : "navItem"} onClick={() => setView("applications")}>
            <AppstoreOutlined /> 应用中心
          </button>
          <button className="navItem disabled"><DeploymentUnitOutlined /> 能力中心 <span>即将接入</span></button>
          <button className="navItem disabled"><SettingOutlined /> 设置 <span>即将接入</span></button>
        </nav>
        <div className="sidebarFoot">v0.1 · dev</div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <div className="eyebrow">AI APPLICATION HUB</div>
            <h1>{view === "overview" ? "AI 应用中枢" : "应用中心"}</h1>
          </div>
          <div className={hubHealthy ? "health good" : "health warning"}>
            <span className="dot" />
            {hubHealthy === null ? "检查中" : hubHealthy ? "Hub API 正常" : "Hub API 未连接"}
          </div>
        </header>

        {error && <div className="alert">{error}。请确认 FastAPI 已在 8000 端口启动。</div>}

        {view === "overview" ? (
          <>
            <section className="hero">
              <div>
                <div className="eyebrow light">UNIFIED WORKSPACE</div>
                <h2>应用独立运行，能力统一接入</h2>
                <p>Lyra Hub 管应用入口、配置和平台能力；Gateway 管模型，Agent OS 管智能执行。</p>
              </div>
              <div className="heroStats">
                <Stat value={applications.length} label="已注册应用" />
                <Stat value={categories} label="应用分类" />
                <Stat value={hubHealthy ? 1 : 0} label="在线平台服务" />
              </div>
            </section>

            <section className="section">
              <div className="sectionHead"><div><h3>我的应用</h3><p>来自 App Manifest v1 的实时注册结果</p></div><button className="linkButton" onClick={() => setView("applications")}>管理全部应用 →</button></div>
              <div className="appGrid">
                {applications.map((app) => <ApplicationCard key={app.id} app={app} />)}
              </div>
            </section>

            <section className="statusGrid">
              <StatusCard title="Gateway" status="待接入" description="模型、Provider、路由、配额和用量" />
              <StatusCard title="Agent OS" status="待接入" description="Agent、Skill、Tool、Workflow 与运行治理" />
              <StatusCard title="Hub Registry" status={applications.length ? "正常" : "待启动"} description="Manifest 校验与应用发现" />
            </section>
          </>
        ) : (
          <section className="section">
            <div className="sectionHead"><div><h3>已注册应用</h3><p>第一阶段先完成发现、校验、查看与启动；启停和持久化配置进入下一批。</p></div></div>
            <div className="table">
              <div className="tableRow tableHead"><span>应用</span><span>类型</span><span>版本</span><span>接入模式</span><span>状态</span><span>操作</span></div>
              {applications.map((app) => (
                <div className="tableRow" key={app.id}>
                  <span><strong>{app.name}</strong><small>{app.id}</small></span>
                  <span>{app.category}</span><span>{app.version}</span><span>{app.integration_type}</span>
                  <span className="statusText">● 已注册</span>
                  <span><a href={app.standalone_url} target="_blank" rel="noreferrer">独立打开</a></span>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return <div className="stat"><strong>{value}</strong><span>{label}</span></div>;
}

function ApplicationCard({ app }: { app: ApplicationSummary }) {
  return (
    <article className="appCard">
      <div className="appIcon">{app.name.slice(0, 1)}</div>
      <div className="appInfo">
        <div className="appTitle"><h4>{app.name}</h4><span>v{app.version}</span></div>
        <p>{app.description || "独立业务 AI 应用"}</p>
        <div className="meta"><span>{app.category}</span><span>{app.integration_type}</span><span className="statusText">● 已注册</span></div>
      </div>
      <a className="openButton" href={app.standalone_url} target="_blank" rel="noreferrer">打开</a>
    </article>
  );
}

function StatusCard({ title, status, description }: { title: string; status: string; description: string }) {
  const good = status === "正常";
  return <article className="statusCard"><div><span className="eyebrow">{title}</span><h4>{description}</h4></div><span className={good ? "pill goodPill" : "pill"}>{status}</span></article>;
}
