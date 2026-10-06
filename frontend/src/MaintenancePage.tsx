import { useCallback, useEffect, useMemo, useState } from "react";

import {
  acknowledgeMaintenanceAlert,
  confirmMaintenanceRepair,
  getMaintenanceOverview,
  HubApiError,
  listMaintenanceAlerts,
  listPlatformConnections,
  runMaintenanceChecks,
  type PlatformConnection,
} from "./api";
import { AdminTokenControl } from "./AdminTokenControl";
import type { MaintenanceAlert, MaintenanceOverview, MaintenanceServiceId } from "./types";

const SERVICES: Array<{ id: MaintenanceServiceId; name: string }> = [
  { id: "hub", name: "Lyra Hub" },
  { id: "gateway", name: "Gateway" },
  { id: "agents", name: "Agents" },
  { id: "narrative", name: "Narrative" },
  { id: "print", name: "Print" },
];

function describeError(error: unknown): string {
  if (error instanceof HubApiError) {
    if (error.status === 401 || error.status === 403) return `无权访问：${error.message}`;
    if (error.message.includes("LYRA_HUB_ADMIN_TOKEN")) return "平台管理员未授权：请配置 Hub 管理令牌并保存到当前会话。";
    if (error.code === "AGENTS_PLATFORM_CREDENTIAL_MISSING") return "Agents 平台管理凭据未配置，请先完成服务端连接配置。";
    if (error.code === "AGENTS_UNAVAILABLE" || error.code === "AGENTS_TIMEOUT") {
      return "Agents 服务暂不可用，请确认 Agents 已启动并检查连接配置。";
    }
  }
  return error instanceof Error ? error.message : "维护信息加载失败";
}

function statusLabel(status: string): string {
  switch (status) {
    case "healthy": return "正常";
    case "empty_catalog": return "目录为空";
    case "unhealthy": return "异常";
    default: return "尚未巡检";
  }
}

function statusClass(status: string): string {
  if (status === "healthy") return "goodPill";
  if (status === "unhealthy") return "badPill";
  return "";
}

function makeIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `repair-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function MaintenancePage() {
  const [overview, setOverview] = useState<MaintenanceOverview | null>(null);
  const [alerts, setAlerts] = useState<MaintenanceAlert[]>([]);
  const [connections, setConnections] = useState<PlatformConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [repair, setRepair] = useState<{ service: "gateway" | "agent-os"; revision: number } | null>(null);
  const [repairConfirmed, setRepairConfirmed] = useState(false);
  const [repairIdempotencyKey, setRepairIdempotencyKey] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const [overviewResult, alertsResult, connectionsResult] = await Promise.allSettled([
      getMaintenanceOverview(),
      listMaintenanceAlerts(),
      listPlatformConnections(),
    ]);
    if (overviewResult.status === "fulfilled") setOverview(overviewResult.value.data);
    if (alertsResult.status === "fulfilled") setAlerts(alertsResult.value.data);
    if (connectionsResult.status === "fulfilled") setConnections(connectionsResult.value);
    const failure = [overviewResult, alertsResult, connectionsResult].find((result) => result.status === "rejected");
    if (failure?.status === "rejected") setError(describeError(failure.reason));
    setLoading(false);
    return connectionsResult.status === "fulfilled";
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const connectionsById = useMemo(
    () => new Map(connections.map((connection) => [connection.service_id, connection])),
    [connections],
  );

  async function triggerCheck() {
    setBusy("checks");
    setError("");
    setNotice("");
    try {
      await runMaintenanceChecks();
      setNotice("巡检已完成，状态和告警已更新。");
      await refresh();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  async function acknowledge(alert: MaintenanceAlert) {
    setBusy(`alert-${alert.id}`);
    setError("");
    try {
      await acknowledgeMaintenanceAlert(alert.id);
      await refresh();
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  function openRepair(service: "gateway" | "agent-os") {
    const connection = connectionsById.get(service);
    if (!connection?.has_last_good) return;
    setRepair({ service, revision: connection.revision });
    setRepairConfirmed(false);
    setRepairIdempotencyKey(makeIdempotencyKey());
  }

  async function confirmRestore() {
    if (!repair || !repairConfirmed) return;
    setBusy(`repair-${repair.service}`);
    setError("");
    try {
      const result = await confirmMaintenanceRepair(
        repair.service,
        { action: "restore_last_good", expected_revision: repair.revision, confirmed: true },
        repairIdempotencyKey ?? makeIdempotencyKey(),
      );
      setNotice(
        result.data.verification_status === "healthy"
          ? `${repair.service === "agent-os" ? "Agents" : "Gateway"} 配置已恢复并通过复检。`
          : `${repair.service === "agent-os" ? "Agents" : "Gateway"} 配置已恢复，但复检仍异常。`,
      );
      setRepair(null);
      setRepairConfirmed(false);
      setRepairIdempotencyKey(null);
      await refresh();
    } catch (reason) {
      if (reason instanceof HubApiError && reason.status === 409) {
        setRepair(null);
        setRepairConfirmed(false);
        setRepairIdempotencyKey(null);
        const refreshed = await refresh();
        setError(refreshed
          ? "配置版本已变化。页面已刷新当前版本，请核对后重新发起确认。"
          : "配置版本已变化，但无法读取最新连接版本。请重试刷新维护信息后再确认。",
        );
      } else {
        setError(describeError(reason));
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="maintenancePage">
      <div className="sectionHead pageHeading">
        <div>
          <h2>平台维护</h2>
          <p>自动巡检每 5 分钟运行。手动巡检只读取服务健康与目录状态。</p>
        </div>
        <button className="primaryButton" disabled={busy !== null} onClick={() => void triggerCheck()}>
          {busy === "checks" ? "正在巡检…" : "立即巡检"}
        </button>
      </div>

      <AdminTokenControl onSaved={() => { void refresh(); }} />
      {error && <div className="alert" role="alert">{error}</div>}
      {notice && <div className="inlineStatus good" role="status">{notice}</div>}
      {loading && <div className="emptyState" role="status">正在加载维护状态…</div>}

      <section className="section">
        <div className="sectionHead">
          <div>
            <h3>服务巡检</h3>
            <p>{overview?.schedule?.enabled ? "自动巡检已启用" : "自动巡检状态未知或未启用"} · 最近一次：{overview?.schedule?.last_run_at ? new Date(overview.schedule.last_run_at).toLocaleString() : "暂无记录"}</p>
          </div>
          <span className="pill">未处理告警 {overview?.open_alerts ?? 0}</span>
        </div>
        <div className="maintenanceServiceGrid">
          {SERVICES.map((service) => {
            const status = overview?.services[service.id]?.status ?? "unknown";
            const checks = Object.values(overview?.services[service.id]?.checks ?? {});
            return (
              <article className="maintenanceService" key={service.id}>
                <div className="maintenanceServiceHead">
                  <strong>{service.name}</strong>
                  <span className={`pill ${statusClass(status)}`}>{statusLabel(status)}</span>
                </div>
                {checks.length === 0 ? <small>尚无巡检结果</small> : checks.map((check) => (
                  <div className="maintenanceCheck" key={check.check_name}>
                    <span>{check.check_name}</span>
                    <span>{statusLabel(check.status)}{check.error_code ? ` · ${check.error_code}` : ""}</span>
                  </div>
                ))}
                {overview?.services[service.id]?.checked_at && (
                  <small>检查时间：{new Date(overview.services[service.id].checked_at!).toLocaleString()}</small>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section className="section">
        <div className="sectionHead">
          <div><h3>告警</h3><p>连续失败两次后生成告警；成功巡检后自动恢复。</p></div>
        </div>
        {alerts.length === 0 ? <div className="emptyState">暂无告警</div> : (
          <div className="maintenanceAlertList">
            {alerts.map((alert) => (
              <article className="maintenanceAlert" key={alert.id}>
                <div>
                  <strong>{alert.service_id} · {alert.check_name}</strong>
                  <small>{alert.error_code} · 连续失败 {alert.consecutive_failures} 次 · {new Date(alert.last_occurred_at).toLocaleString()}</small>
                </div>
                <div className="inlineActions">
                  <span className={`pill ${alert.status === "resolved" ? "goodPill" : alert.status === "open" ? "badPill" : ""}`}>
                    {alert.status === "open" ? "待确认" : alert.status === "acknowledged" ? "已确认" : "已恢复"}
                  </span>
                  {alert.status === "open" && (
                    <button className="secondaryButton compactButton" disabled={busy !== null} onClick={() => void acknowledge(alert)}>
                      {busy === `alert-${alert.id}` ? "处理中…" : "确认告警"}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <div className="sectionHead">
          <div><h3>配置恢复</h3><p>仅恢复 Gateway 或 Agents 的最近可用连接配置；确认前不会写入。</p></div>
        </div>
        <div className="maintenanceRepairGrid">
          {(["gateway", "agent-os"] as const).map((service) => {
            const connection = connectionsById.get(service);
            const label = service === "agent-os" ? "Agents" : "Gateway";
            return (
              <article className="maintenanceRepairCard" key={service}>
                <div><strong>{label}</strong><small>配置版本 {connection?.revision ?? 0}</small></div>
                <span className="pill">{connection?.credential_configured ? "凭据已配置" : "未配置凭据"}</span>
                <button
                  className="secondaryButton"
                  disabled={!connection?.has_last_good || busy !== null}
                  onClick={() => openRepair(service)}
                >
                  恢复最近可用配置
                </button>
                {!connection?.has_last_good && <small>暂无可恢复快照</small>}
              </article>
            );
          })}
        </div>
      </section>

      {repair && (
        <div className="confirmBackdrop">
          <section className="confirmDialog" role="dialog" aria-modal="true" aria-labelledby="repair-title">
            <h3 id="repair-title">二次确认恢复配置</h3>
            <p>将恢复 {repair.service === "agent-os" ? "Agents" : "Gateway"} 最近可用配置。确认前不会更改配置。</p>
            <p>预期配置版本：<strong>{repair.revision}</strong></p>
            <label className="confirmationCheck">
              <input checked={repairConfirmed} onChange={(event) => setRepairConfirmed(event.target.checked)} type="checkbox" />
              我已检查目标服务和配置版本，并确认恢复
            </label>
            <div className="inlineActions">
              <button className="secondaryButton" disabled={busy !== null} onClick={() => { setRepair(null); setRepairConfirmed(false); setRepairIdempotencyKey(null); }}>取消</button>
              <button className="dangerButton" disabled={!repairConfirmed || busy !== null} onClick={() => void confirmRestore()}>
                {busy === `repair-${repair.service}` ? "正在恢复…" : "确认恢复"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
