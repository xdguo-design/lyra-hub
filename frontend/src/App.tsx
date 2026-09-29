import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AppstoreAddOutlined,
  AppstoreOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  SlidersOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import {
  getApplication,
  getHubHealth,
  getPlatformStatus,
  invokeCapability,
  launchApplication,
  listApplicationPages,
  listApplications,
  listAuditEvents,
  listCapabilities,
  listNavigation,
  listPageConfiguration,
  listPlugins,
  setApplicationEnabled,
  updateApplicationPage,
  updatePlugin,
  updatePageConfiguration,
} from "./api";
import type {
  ApplicationDetail,
  ApplicationPageConfig,
  ApplicationPageItemConfig,
  ApplicationSummary,
  AuditEvent,
  CapabilityInfo,
  PluginSummary,
  ServiceStatus,
} from "./types";

type View =
  | "overview"
  | "applications"
  | "application"
  | "plugins"
  | "page-config"
  | "capabilities"
  | "permissions"
  | "operations"
  | "settings";

export function App() {
  const [view, setView] = useState<View>("overview");
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [navigationApps, setNavigationApps] = useState<ApplicationSummary[]>([]);
  const [selected, setSelected] = useState<ApplicationDetail | null>(null);
  const [pageConfigs, setPageConfigs] = useState<ApplicationPageConfig[]>([]);
  const [pageItems, setPageItems] = useState<Record<string, ApplicationPageItemConfig[]>>({});
  const [capabilities, setCapabilities] = useState<CapabilityInfo[]>([]);
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const [platformStatus, setPlatformStatus] = useState<ServiceStatus[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [hubHealthy, setHubHealthy] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [busyApp, setBusyApp] = useState<string | null>(null);
  const [busyPlugin, setBusyPlugin] = useState<string | null>(null);
  const [roleInput, setRoleInput] = useState("writer");
  const [rolePreview, setRolePreview] = useState<ApplicationSummary[]>([]);
  const [capabilityResult, setCapabilityResult] = useState("");

  const refreshCore = useCallback(async () => {
    const [apps, nav, healthy] = await Promise.all([
      listApplications(),
      listNavigation(),
      getHubHealth(),
    ]);
    setApplications(apps);
    setNavigationApps(nav);
    setHubHealthy(healthy);
    return apps;
  }, []);

  useEffect(() => {
    void refreshCore().catch((reason: unknown) => {
      setHubHealthy(false);
      setError(reason instanceof Error ? reason.message : "加载失败");
    });
  }, [refreshCore]);

  const categories = useMemo(
    () => new Set(applications.map((app) => app.category)).size,
    [applications],
  );
  const enabledCount = useMemo(
    () => applications.filter((app) => app.enabled).length,
    [applications],
  );

  async function openDetail(appId: string) {
    setError("");
    try {
      setSelected(await getApplication(appId));
      setView("application");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "应用详情加载失败");
    }
  }

  async function toggleEnabled(appItem: ApplicationSummary | ApplicationDetail) {
    setBusyApp(appItem.id);
    setError("");
    try {
      const detail = await setApplicationEnabled(appItem.id, !appItem.enabled);
      setSelected((current) => (current?.id === detail.id ? detail : current));
      await refreshCore();
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

  async function openPlugins() {
    setError("");
    try {
      setPlugins(await listPlugins());
      setView("plugins");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "插件中心加载失败");
    }
  }

  async function togglePlugin(plugin: PluginSummary) {
    setBusyPlugin(plugin.id);
    setError("");
    try {
      const saved = await updatePlugin(plugin.id, {
        enabled: !plugin.enabled,
        granted_permissions: plugin.enabled
          ? plugin.granted_permissions
          : plugin.permissions,
      });
      setPlugins((current) =>
        current.map((item) => (item.id === saved.id ? saved : item)),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "插件状态更新失败");
    } finally {
      setBusyPlugin(null);
    }
  }

  async function openPageConfiguration() {
    setError("");
    try {
      const configs = await listPageConfiguration();
      const items = await Promise.all(
        configs.map(async (config) => [
          config.app_id,
          await listApplicationPages(config.app_id),
        ] as const),
      );
      setPageConfigs(configs);
      setPageItems(Object.fromEntries(items));
      setView("page-config");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "页面配置加载失败");
    }
  }

  async function savePageConfiguration(
    appId: string,
    update: Partial<Omit<ApplicationPageConfig, "app_id">>,
  ) {
    setError("");
    try {
      const saved = await updatePageConfiguration(appId, update);
      setPageConfigs((current) =>
        current.map((item) => (item.app_id === appId ? saved : item)),
      );
      await refreshCore();
      if (selected?.id === appId) {
        setSelected(await getApplication(appId));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "页面配置保存失败");
      throw reason;
    }
  }

  async function saveApplicationPage(
    appId: string,
    pageId: string,
    update: Partial<Omit<ApplicationPageItemConfig, "app_id" | "page_id" | "path">>,
  ) {
    setError("");
    try {
      const saved = await updateApplicationPage(appId, pageId, update);
      setPageItems((current) => ({
        ...current,
        [appId]: (current[appId] ?? []).map((item) =>
          item.page_id === pageId ? saved : item,
        ),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "页面项配置保存失败");
      throw reason;
    }
  }

  async function openCapabilities() {
    setError("");
    try {
      const [items, statuses] = await Promise.all([
        listCapabilities(),
        getPlatformStatus(),
      ]);
      setCapabilities(items);
      setPlatformStatus(statuses);
      setView("capabilities");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "能力中心加载失败");
    }
  }

  async function testCapability(name: string) {
    setError("");
    setCapabilityResult("");
    try {
      const result = await invokeCapability(name);
      setCapabilityResult(JSON.stringify(result, null, 2));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "能力调用失败");
    }
  }

  async function openOperations() {
    setError("");
    try {
      const [events, statuses] = await Promise.all([
        listAuditEvents(),
        getPlatformStatus(),
      ]);
      setAuditEvents(events);
      setPlatformStatus(statuses);
      setView("operations");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运行信息加载失败");
    }
  }

  async function openSettings() {
    setError("");
    try {
      setPlatformStatus(await getPlatformStatus());
      setView("settings");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "设置加载失败");
    }
  }

  async function previewRoleVisibility() {
    setError("");
    try {
      setRolePreview(await listNavigation(roleInput));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "角色预览失败");
    }
  }

  const pageTitle =
    view === "overview"
      ? "AI 应用中枢"
      : view === "applications"
        ? "应用中心"
        : view === "application"
          ? selected?.name ?? "应用详情"
          : view === "plugins"
            ? "插件中心"
            : view === "page-config"
              ? "页面配置"
            : view === "capabilities"
              ? "能力中心"
              : view === "permissions"
                ? "用户与权限"
                : view === "operations"
                  ? "运行与审计"
                  : "设置";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">L</span>
          <span>Lyra Hub</span>
        </div>
        <div className="eyebrow">WORKSPACE</div>
        <nav>
          <NavButton
            active={view === "overview"}
            icon={<DashboardOutlined />}
            label="总览"
            onClick={() => setView("overview")}
          />
          <NavButton
            active={view === "applications" || view === "application"}
            icon={<AppstoreOutlined />}
            label="应用中心"
            onClick={() => setView("applications")}
          />
          <NavButton
            active={view === "plugins"}
            icon={<AppstoreAddOutlined />}
            label="插件中心"
            onClick={() => void openPlugins()}
          />
          <NavButton
            active={view === "page-config"}
            icon={<SlidersOutlined />}
            label="页面配置"
            onClick={() => void openPageConfiguration()}
          />
          <NavButton
            active={view === "capabilities"}
            icon={<ThunderboltOutlined />}
            label="能力中心"
            onClick={() => void openCapabilities()}
          />
          <NavButton
            active={view === "permissions"}
            icon={<SafetyCertificateOutlined />}
            label="用户与权限"
            onClick={() => setView("permissions")}
          />
          <NavButton
            active={view === "operations"}
            icon={<DeploymentUnitOutlined />}
            label="运行与审计"
            onClick={() => void openOperations()}
          />
          <NavButton
            active={view === "settings"}
            icon={<SettingOutlined />}
            label="设置"
            onClick={() => void openSettings()}
          />
        </nav>

        <div className="eyebrow appNavLabel">APPLICATIONS</div>
        <div className="generatedNav">
          {navigationApps.map((appItem) => (
            <button key={appItem.id} onClick={() => void openDetail(appItem.id)}>
              <span>{appItem.name.slice(0, 1)}</span>
              <strong>{appItem.name}</strong>
            </button>
          ))}
        </div>
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
            {hubHealthy === null
              ? "检查中"
              : hubHealthy
                ? "Hub API 正常"
                : "Hub API 未连接"}
          </div>
        </header>

        {error && <div className="alert">{error}</div>}

        {view === "overview" && (
          <>
            <section className="hero">
              <div>
                <div className="eyebrow light">UNIFIED WORKSPACE</div>
                <h2>应用独立运行，能力统一接入</h2>
                <p>
                  Lyra Hub 管应用入口、导航、权限可见性和平台能力；Gateway
                  管模型，Agent OS 管智能执行。
                </p>
              </div>
              <div className="heroStats">
                <Stat value={applications.length} label="已注册应用" />
                <Stat value={enabledCount} label="已启用" />
                <Stat value={categories} label="应用分类" />
              </div>
            </section>

            <section className="section">
              <div className="sectionHead">
                <div>
                  <h3>我的应用</h3>
                  <p>这里直接使用 Registry + Page Configuration 生成导航。</p>
                </div>
                <button
                  className="linkButton"
                  onClick={() => setView("applications")}
                >
                  管理全部应用 →
                </button>
              </div>
              <div className="appGrid">
                {navigationApps.map((appItem) => (
                  <ApplicationCard
                    key={appItem.id}
                    app={appItem}
                    busy={busyApp === appItem.id}
                    onManage={() => void openDetail(appItem.id)}
                    onLaunch={() => void launch(appItem.id)}
                  />
                ))}
              </div>
            </section>

            <section className="statusGrid">
              <StatusCard
                title="Gateway"
                status="已接入"
                description="模型、Provider、路由、配额和生成能力由适配器统一调用"
              />
              <StatusCard
                title="Agent OS"
                status="已接入"
                description="Agent 查询与运行能力已通过平台适配器接入"
              />
              <StatusCard
                title="Hub Registry"
                status="正常"
                description="Manifest、持久化状态、页面配置和动态导航"
              />
            </section>
          </>
        )}

        {view === "applications" && (
          <section className="section">
            <div className="sectionHead">
              <div>
                <h3>已注册应用</h3>
                <p>启停由 Hub 持久化，不修改业务应用源码。</p>
              </div>
            </div>
            <div className="table">
              <div className="tableRow tableHead">
                <span>应用</span>
                <span>类型</span>
                <span>版本</span>
                <span>接入模式</span>
                <span>状态</span>
                <span>操作</span>
              </div>
              {applications.map((appItem) => (
                <div className="tableRow" key={appItem.id}>
                  <span>
                    <strong>{appItem.name}</strong>
                    <small>{appItem.id}</small>
                  </span>
                  <span>{appItem.category}</span>
                  <span>{appItem.version}</span>
                  <span>{appItem.integration_type}</span>
                  <span
                    className={
                      appItem.enabled
                        ? "statusText"
                        : "statusText disabledText"
                    }
                  >
                    {appItem.enabled ? "● 已启用" : "● 已停用"}
                  </span>
                  <span className="rowActions">
                    <button
                      className="textAction"
                      onClick={() => void openDetail(appItem.id)}
                    >
                      管理
                    </button>
                    <button
                      className="textAction"
                      disabled={!appItem.enabled || busyApp === appItem.id}
                      onClick={() => void launch(appItem.id)}
                    >
                      打开
                    </button>
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
                <span
                  className={
                    selected.enabled ? "pill goodPill" : "pill"
                  }
                >
                  {selected.enabled ? "已启用" : "已停用"}
                </span>
              </div>

              <div className="detailActions">
                <button
                  className="primaryButton"
                  disabled={!selected.enabled || busyApp === selected.id}
                  onClick={() => void launch(selected.id)}
                >
                  从 Hub 打开
                </button>
                <button
                  className={
                    selected.enabled ? "dangerButton" : "secondaryButton"
                  }
                  disabled={busyApp === selected.id}
                  onClick={() => void toggleEnabled(selected)}
                >
                  {selected.enabled ? "停用应用" : "启用应用"}
                </button>
              </div>

              <div className="infoGrid">
                <Info label="版本" value={selected.version} />
                <Info label="接入模式" value={selected.integration_type} />
                <Info label="默认启动" value={selected.default_launch_mode} />
                <Info label="导航分组" value={selected.navigation_group} />
                <Info label="Workspace 路径" value={selected.workspace_path} />
                <Info label="独立入口" value={selected.standalone_url} />
              </div>

              <h3 className="subheading">消费的平台能力</h3>
              <div className="tagList">
                {selected.capabilities_consumed.map((capability) => (
                  <span key={capability}>{capability}</span>
                ))}
              </div>

              <h3 className="subheading">权限声明</h3>
              <div className="tagList">
                {selected.permissions.map((permission) => (
                  <span key={permission}>{permission}</span>
                ))}
              </div>
            </article>

            <aside className="section detailAside">
              <div className="eyebrow">RUNTIME POLICY</div>
              <h3>Hub 管理状态</h3>
              <p>
                停用只影响 Hub 内的发现与启动，不破坏应用自己的独立运行能力。
              </p>
              <div className="policyLine">
                <span>Manifest</span>
                <strong>v1 / 已验证</strong>
              </div>
              <div className="policyLine">
                <span>独立运行</span>
                <strong>保留</strong>
              </div>
              <div className="policyLine">
                <span>Hub 启动</span>
                <strong>{selected.enabled ? "允许" : "禁止"}</strong>
              </div>
              <div className="policyLine">
                <span>导航可见</span>
                <strong>{selected.hidden ? "隐藏" : "显示"}</strong>
              </div>
            </aside>
          </section>
        )}

        {view === "plugins" && (
          <section className="section">
            <div className="sectionHead">
              <div>
                <h3>插件中心</h3>
                <p>
                  插件按 Manifest 注册；启用前必须显式授予它声明的权限，业务应用仍保持独立运行。
                </p>
              </div>
              <span className="pill">{plugins.length} 个插件</span>
            </div>
            <div className="pluginGrid">
              {plugins.map((plugin) => (
                <article
                  className={plugin.enabled ? "pluginCard" : "pluginCard pluginCardDisabled"}
                  key={plugin.id}
                >
                  <div className="pluginHeader">
                    <div className="appIcon small">插</div>
                    <div>
                      <strong>{plugin.name}</strong>
                      <small>{plugin.id} · v{plugin.version}</small>
                    </div>
                    <span className={plugin.enabled ? "pill goodPill" : "pill"}>
                      {plugin.enabled ? "已启用" : "未启用"}
                    </span>
                  </div>
                  <p>{plugin.description || "Lyra Hub 插件"}</p>

                  <div className="pluginSectionLabel">目标应用</div>
                  <div className="tagList">
                    {plugin.target_applications.map((appId) => (
                      <span key={appId}>{appId}</span>
                    ))}
                  </div>

                  <div className="pluginSectionLabel">所需权限</div>
                  <div className="tagList">
                    {plugin.permissions.map((permission) => (
                      <span key={permission}>{permission}</span>
                    ))}
                  </div>

                  <div className="pluginContributions">
                    <span>{plugin.contributions.widgets.length} Widgets</span>
                    <span>{plugin.contributions.actions.length} Actions</span>
                    <span>{plugin.contributions.slots.length} Slots</span>
                    <span>{plugin.capabilities_consumed.length} Capabilities</span>
                  </div>

                  <button
                    className={plugin.enabled ? "secondaryButton" : "primaryButton"}
                    disabled={busyPlugin === plugin.id}
                    onClick={() => void togglePlugin(plugin)}
                  >
                    {busyPlugin === plugin.id
                      ? "处理中…"
                      : plugin.enabled
                        ? "停用插件"
                        : "授权并启用"}
                  </button>
                </article>
              ))}
            </div>
          </section>
        )}

        {view === "page-config" && (
          <section className="section">
            <div className="sectionHead">
              <div>
                <h3>统一页面配置</h3>
                <p>
                  只控制 Hub 展示和启动策略，不侵入小说、打印、医院 AI 自己的业务页面。
                </p>
              </div>
            </div>
            <div className="configGrid">
              {pageConfigs.map((config) => {
                const appItem = applications.find(
                  (item) => item.id === config.app_id,
                );
                return (
                  <PageConfigCard
                    key={config.app_id}
                    config={config}
                    app={appItem}
                    onSave={(update) =>
                      savePageConfiguration(config.app_id, update)
                    }
                  />
                );
              })}
            </div>

            <div className="pageItemSection">
              <div className="sectionHead compactHead">
                <div>
                  <h3>应用内部页面入口</h3>
                  <p>
                    这些配置只改变 Hub 中的入口名称、顺序和可见性，不改业务应用自己的路由实现。
                  </p>
                </div>
              </div>
              {pageConfigs.map((config) => {
                const appItem = applications.find(
                  (item) => item.id === config.app_id,
                );
                const items = pageItems[config.app_id] ?? [];
                return (
                  <div className="pageItemGroup" key={config.app_id}>
                    <div className="pageItemGroupTitle">
                      <strong>{appItem?.name ?? config.app_id}</strong>
                      <span>{items.length} 个页面</span>
                    </div>
                    {items.length === 0 ? (
                      <div className="emptyState compactEmpty">
                        Manifest 暂未声明页面。
                      </div>
                    ) : (
                      <div className="pageItemList">
                        {items.map((item) => (
                          <PageItemConfigRow
                            key={item.page_id}
                            item={item}
                            onSave={(update) =>
                              saveApplicationPage(
                                config.app_id,
                                item.page_id,
                                update,
                              )
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {view === "capabilities" && (
          <>
            <section className="platformGrid">
              {platformStatus.map((service) => (
                <article className="section platformCard" key={service.id}>
                  <div className="sectionHead">
                    <div>
                      <div className="eyebrow">{service.id}</div>
                      <h3>{service.name}</h3>
                    </div>
                    <span
                      className={
                        service.reachable ? "pill goodPill" : "pill badPill"
                      }
                    >
                      {service.reachable ? "在线" : "不可达"}
                    </span>
                  </div>
                  <code>{service.base_url}</code>
                </article>
              ))}
            </section>

            <section className="section">
              <div className="sectionHead">
                <div>
                  <h3>平台能力</h3>
                  <p>
                    应用只消费统一 capability contract，不直接依赖 Gateway 或
                    Agent OS 内部模块。
                  </p>
                </div>
              </div>
              <div className="capabilityGrid">
                {capabilities.map((capability) => (
                  <article className="capabilityCard" key={capability.name}>
                    <div>
                      <strong>{capability.name}</strong>
                      <p>{capability.description}</p>
                    </div>
                    <div className="capabilityMeta">
                      <span>{capability.source}</span>
                      <span>
                        {capability.mutation ? "写操作" : "只读"}
                      </span>
                      <span
                        className={
                          capability.reachable
                            ? "statusText"
                            : "disabledText"
                        }
                      >
                        {capability.reachable ? "● 可连接" : "● 离线"}
                      </span>
                    </div>
                    {(capability.name === "model.list" ||
                      capability.name === "agent.list") && (
                      <button
                        className="secondaryButton compactButton"
                        onClick={() => void testCapability(capability.name)}
                      >
                        实际调用
                      </button>
                    )}
                  </article>
                ))}
              </div>
              {capabilityResult && (
                <pre className="resultPanel">{capabilityResult}</pre>
              )}
            </section>
          </>
        )}

        {view === "permissions" && (
          <section className="section">
            <div className="sectionHead">
              <div>
                <h3>角色可见性</h3>
                <p>
                  MVP 先验证 Hub 角色到应用导航可见性的映射；业务操作最终授权仍由各应用负责。
                </p>
              </div>
            </div>
            <div className="roleTester">
              <label>
                <span>模拟角色</span>
                <input
                  value={roleInput}
                  onChange={(event) => setRoleInput(event.target.value)}
                  placeholder="writer,operator"
                />
              </label>
              <button
                className="primaryButton"
                onClick={() => void previewRoleVisibility()}
              >
                预览可见应用
              </button>
            </div>
            <div className="rolePreview">
              {rolePreview.length === 0 ? (
                <div className="emptyState">输入角色后执行预览。</div>
              ) : (
                rolePreview.map((appItem) => (
                  <div className="roleApp" key={appItem.id}>
                    <span>{appItem.name.slice(0, 1)}</span>
                    <div>
                      <strong>{appItem.name}</strong>
                      <small>
                        {appItem.visible_roles.length
                          ? appItem.visible_roles.join(", ")
                          : "所有角色"}
                      </small>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        {view === "operations" && (
          <>
            <section className="platformGrid">
              {platformStatus.map((service) => (
                <article className="section platformCard" key={service.id}>
                  <div className="sectionHead">
                    <div>
                      <div className="eyebrow">{service.id}</div>
                      <h3>{service.name}</h3>
                    </div>
                    <span
                      className={
                        service.reachable ? "pill goodPill" : "pill badPill"
                      }
                    >
                      {service.reachable ? "在线" : "不可达"}
                    </span>
                  </div>
                  <code>{service.base_url}</code>
                </article>
              ))}
            </section>

            <section className="section">
              <div className="sectionHead">
                <div>
                  <h3>配置审计</h3>
                  <p>记录应用启停和页面配置变更。</p>
                </div>
              </div>
              {auditEvents.length === 0 ? (
                <div className="emptyState">还没有配置变更记录。</div>
              ) : (
                <div className="auditList">
                  {auditEvents.map((event) => (
                    <div className="auditRow" key={event.id}>
                      <span className="auditIcon">↳</span>
                      <div>
                        <strong>{event.action}</strong>
                        <small>
                          {event.target_type} · {event.target_id}
                        </small>
                      </div>
                      <time>
                        {new Date(event.created_at).toLocaleString()}
                      </time>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        {view === "settings" && (
          <section className="section">
            <div className="sectionHead">
              <div>
                <h3>平台连接设置</h3>
                <p>
                  Token 只保存在后端环境变量中，不通过浏览器或 Manifest 暴露。
                </p>
              </div>
            </div>
            <div className="settingsList">
              {platformStatus.map((service) => (
                <div className="settingRow" key={service.id}>
                  <div>
                    <strong>{service.name}</strong>
                    <small>{service.base_url}</small>
                  </div>
                  <span
                    className={
                      service.reachable ? "pill goodPill" : "pill badPill"
                    }
                  >
                    {service.reachable ? "连接正常" : "等待服务"}
                  </span>
                </div>
              ))}
            </div>
            <div className="envHelp">
              <strong>后端环境变量</strong>
              <code>LYRA_GATEWAY_URL / LYRA_GATEWAY_TOKEN</code>
              <code>
                LYRA_AGENT_OS_URL / LYRA_AGENT_OS_TOKEN /
                LYRA_AGENT_RUNTIME_TOKEN
              </code>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

function NavButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button className={active ? "navItem active" : "navItem"} onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
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
        <div className="appTitle">
          <h4>{app.name}</h4>
          <span>v{app.version}</span>
        </div>
        <p>{app.description || "独立业务 AI 应用"}</p>
        <div className="meta">
          <span>{app.category}</span>
          <span>{app.integration_type}</span>
          <span className={app.enabled ? "statusText" : "disabledText"}>
            {app.enabled ? "● 已启用" : "● 已停用"}
          </span>
        </div>
        <div className="cardActions">
          <button className="textAction" onClick={onManage}>
            管理
          </button>
          <button
            className="textAction"
            disabled={!app.enabled || busy}
            onClick={onLaunch}
          >
            打开
          </button>
        </div>
      </div>
    </article>
  );
}

function StatusCard({
  title,
  status,
  description,
}: {
  title: string;
  status: string;
  description: string;
}) {
  const good = status === "正常" || status === "已接入";
  return (
    <article className="statusCard">
      <div>
        <span className="eyebrow">{title}</span>
        <h4>{description}</h4>
      </div>
      <span className={good ? "pill goodPill" : "pill"}>{status}</span>
    </article>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="infoItem">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PageConfigCard({
  config,
  app,
  onSave,
}: {
  config: ApplicationPageConfig;
  app?: ApplicationSummary;
  onSave: (
    update: Partial<Omit<ApplicationPageConfig, "app_id">>,
  ) => Promise<void>;
}) {
  const [nameOverride, setNameOverride] = useState(config.name_override ?? "");
  const [group, setGroup] = useState(config.navigation_group);
  const [order, setOrder] = useState(String(config.navigation_order));
  const [roles, setRoles] = useState(config.visible_roles.join(", "));
  const [hidden, setHidden] = useState(config.hidden);
  const [launchMode, setLaunchMode] = useState<
    "workspace" | "standalone"
  >(config.default_launch_mode);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setNameOverride(config.name_override ?? "");
    setGroup(config.navigation_group);
    setOrder(String(config.navigation_order));
    setRoles(config.visible_roles.join(", "));
    setHidden(config.hidden);
    setLaunchMode(config.default_launch_mode);
  }, [config]);

  async function save() {
    setSaving(true);
    try {
      await onSave({
        name_override: nameOverride.trim() || null,
        navigation_group: group.trim() || "Applications",
        navigation_order: Number(order) || 0,
        visible_roles: roles
          .split(",")
          .map((role) => role.trim())
          .filter(Boolean),
        hidden,
        default_launch_mode: launchMode,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="configCard">
      <div className="configTitle">
        <div className="appIcon small">{(app?.name ?? config.app_id).slice(0, 1)}</div>
        <div>
          <strong>{app?.name ?? config.app_id}</strong>
          <small>{config.app_id}</small>
        </div>
      </div>
      <label>
        <span>名称覆盖</span>
        <input
          value={nameOverride}
          onChange={(event) => setNameOverride(event.target.value)}
          placeholder={app?.name ?? ""}
        />
      </label>
      <div className="fieldPair">
        <label>
          <span>导航分组</span>
          <input value={group} onChange={(event) => setGroup(event.target.value)} />
        </label>
        <label>
          <span>顺序</span>
          <input
            type="number"
            value={order}
            onChange={(event) => setOrder(event.target.value)}
          />
        </label>
      </div>
      <label>
        <span>可见角色，逗号分隔；留空表示全部</span>
        <input
          value={roles}
          onChange={(event) => setRoles(event.target.value)}
          placeholder="writer, operator"
        />
      </label>
      <div className="fieldPair">
        <label>
          <span>默认启动方式</span>
          <select
            value={launchMode}
            onChange={(event) =>
              setLaunchMode(event.target.value as "workspace" | "standalone")
            }
          >
            <option value="workspace">Hub Workspace</option>
            <option value="standalone">独立运行</option>
          </select>
        </label>
        <label className="checkboxLabel">
          <input
            type="checkbox"
            checked={hidden}
            onChange={(event) => setHidden(event.target.checked)}
          />
          <span>从 Hub 导航隐藏</span>
        </label>
      </div>
      <button
        className="primaryButton"
        disabled={saving}
        onClick={() => void save()}
      >
        {saving ? "保存中…" : "保存配置"}
      </button>
    </article>
  );
}


function PageItemConfigRow({
  item,
  onSave,
}: {
  item: ApplicationPageItemConfig;
  onSave: (
    update: Partial<Omit<ApplicationPageItemConfig, "app_id" | "page_id" | "path">>,
  ) => Promise<void>;
}) {
  const [title, setTitle] = useState(item.title);
  const [order, setOrder] = useState(String(item.navigation_order));
  const [roles, setRoles] = useState(item.visible_roles.join(", "));
  const [hidden, setHidden] = useState(item.hidden);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setTitle(item.title);
    setOrder(String(item.navigation_order));
    setRoles(item.visible_roles.join(", "));
    setHidden(item.hidden);
  }, [item]);

  async function save() {
    setSaving(true);
    try {
      await onSave({
        title: title.trim() || item.title,
        navigation_order: Number(order) || 0,
        visible_roles: roles
          .split(",")
          .map((role) => role.trim())
          .filter(Boolean),
        hidden,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={hidden ? "pageItemRow pageItemRowHidden" : "pageItemRow"}>
      <div className="pageItemIdentity">
        <strong>{item.page_id}</strong>
        <code>{item.path}</code>
      </div>
      <label>
        <span>显示名称</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        <span>顺序</span>
        <input
          type="number"
          value={order}
          onChange={(event) => setOrder(event.target.value)}
        />
      </label>
      <label>
        <span>可见角色</span>
        <input
          value={roles}
          onChange={(event) => setRoles(event.target.value)}
          placeholder="留空表示全部"
        />
      </label>
      <label className="checkboxLabel pageItemCheckbox">
        <input
          type="checkbox"
          checked={hidden}
          onChange={(event) => setHidden(event.target.checked)}
        />
        <span>隐藏</span>
      </label>
      <button
        className="secondaryButton compactButton"
        disabled={saving}
        onClick={() => void save()}
      >
        {saving ? "保存中…" : "保存"}
      </button>
    </div>
  );
}
