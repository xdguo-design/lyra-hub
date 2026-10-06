import { useCallback, useEffect, useState } from "react";

import {
  createAgentsTenant,
  HubApiError,
  inviteAgentsTenantAdmin,
  listAgentsTenants,
  setAgentsTenantActive,
} from "./api";
import { AdminTokenControl } from "./AdminTokenControl";
import type { AgentsTenant } from "./types";

const PAGE_SIZE = 50;

function describeError(error: unknown): string {
  if (error instanceof HubApiError) {
    if (error.status === 401 || error.status === 403) return `无权访问：${error.message}`;
    if (error.message.includes("LYRA_HUB_ADMIN_TOKEN")) return "平台管理员未授权：请配置 Hub 管理令牌并保存到当前会话。";
    if (error.code === "AGENTS_PLATFORM_CREDENTIAL_MISSING") return "Agents 平台管理凭据未配置，请先完成服务端连接配置。";
    if (error.code === "AGENTS_UNAVAILABLE" || error.code === "AGENTS_TIMEOUT" || error.status === 503) {
      return "Agents 服务暂不可用，请确认 Agents 已启动并检查服务端平台凭据。";
    }
  }
  return error instanceof Error ? error.message : "租户信息加载失败";
}

export function TenantsPage() {
  const [tenants, setTenants] = useState<AgentsTenant[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [inviteFor, setInviteFor] = useState<string | null>(null);
  const [adminEmail, setAdminEmail] = useState("");
  const [invitation, setInvitation] = useState<{ tenantName: string; token: string; expiresIn: number } | null>(null);

  const refresh = useCallback(async (nextOffset = offset) => {
    setLoading(true);
    setError("");
    try {
      const page = await listAgentsTenants(PAGE_SIZE, nextOffset);
      setTenants(page.items);
      setTotal(page.total ?? null);
      setOffset(nextOffset);
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => { void refresh(0); }, []); // Load only; no write is triggered on entry.

  async function createTenant(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("create");
    setError("");
    try {
      await createAgentsTenant({ id: tenantId.trim(), name: tenantName.trim() });
      setTenantId("");
      setTenantName("");
      setInvitation(null);
      await refresh(0);
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  async function toggleTenant(tenant: AgentsTenant) {
    setBusy(tenant.id);
    setError("");
    try {
      const saved = await setAgentsTenantActive(tenant.id, !tenant.active);
      setTenants((current) => current.map((item) => item.id === saved.id ? { ...item, ...saved } : item));
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  async function inviteAdmin(event: React.FormEvent<HTMLFormElement>, tenant: AgentsTenant) {
    event.preventDefault();
    setBusy(`invite-${tenant.id}`);
    setError("");
    try {
      const result = await inviteAgentsTenantAdmin(tenant.id, adminEmail.trim());
      setInvitation({ tenantName: tenant.name, token: result.invitation_token, expiresIn: result.expires_in });
      setInviteFor(null);
      setAdminEmail("");
    } catch (reason) {
      setError(describeError(reason));
    } finally {
      setBusy(null);
    }
  }

  const hasNext = total === null ? tenants.length === PAGE_SIZE : offset + tenants.length < total;

  return (
    <div className="tenantsPage">
      <div className="sectionHead pageHeading">
        <div><h2>Agents 租户</h2><p>租户身份与成员由 Agents 管理；Hub 仅代理平台管理 API。</p></div>
        <button className="secondaryButton" disabled={loading} onClick={() => void refresh(offset)}>刷新</button>
      </div>
      <AdminTokenControl onSaved={() => { void refresh(0); }} />
      {error && <div className="alert" role="alert">{error}</div>}
      {invitation && (
        <div className="inlineStatus good invitationNotice" role="status">
          <strong>{invitation.tenantName} 管理员邀请已创建</strong>
          <span>一次性邀请令牌：<code>{invitation.token}</code></span>
          <small>有效期 {Math.floor(invitation.expiresIn / 3600)} 小时。请安全交付给受邀管理员。</small>
          <button className="textAction" onClick={() => setInvitation(null)}>已安全保存，关闭</button>
        </div>
      )}

      <section className="section">
        <div className="sectionHead"><div><h3>创建租户</h3><p>租户会先在 Agents 建立，Gateway 关联可稍后配置。</p></div></div>
        <form className="tenantCreateForm" onSubmit={(event) => void createTenant(event)}>
          <label>租户 ID<input autoComplete="off" maxLength={128} name="tenantId" onChange={(event) => setTenantId(event.target.value)} required value={tenantId} /></label>
          <label>租户名称<input maxLength={200} name="tenantName" onChange={(event) => setTenantName(event.target.value)} required value={tenantName} /></label>
          <button className="primaryButton" disabled={busy !== null} type="submit">{busy === "create" ? "正在创建…" : "创建租户"}</button>
        </form>
      </section>

      <section className="section">
        <div className="sectionHead"><div><h3>租户列表</h3><p>{total === null ? `每页最多 ${PAGE_SIZE} 个租户` : `共 ${total} 个租户`}</p></div></div>
        {loading && <div className="emptyState" role="status">正在加载 Agents 租户…</div>}
        {!loading && tenants.length === 0 && !error && <div className="emptyState">暂无租户</div>}
        {!loading && tenants.length > 0 && (
          <div className="tenantList">
            {tenants.map((tenant) => (
              <article className="tenantRow" key={tenant.id}>
                <div className="tenantIdentity">
                  <strong>{tenant.name}</strong>
                  <small>{tenant.id} · 创建于 {new Date(tenant.created_at).toLocaleDateString()}</small>
                </div>
                <span className={`pill ${tenant.active ? "goodPill" : "badPill"}`}>{tenant.active ? "启用" : "已停用"}</span>
                <div className="inlineActions">
                  <button className="secondaryButton compactButton" disabled={busy !== null} onClick={() => void toggleTenant(tenant)}>
                    {busy === tenant.id ? "处理中…" : tenant.active ? "停用" : "启用"}
                  </button>
                  <button className="secondaryButton compactButton" disabled={busy !== null} onClick={() => { setInvitation(null); setInviteFor(inviteFor === tenant.id ? null : tenant.id); }}>
                    邀请管理员
                  </button>
                </div>
                {inviteFor === tenant.id && (
                  <form className="tenantInviteForm" onSubmit={(event) => void inviteAdmin(event, tenant)}>
                    <label>管理员邮箱<input autoComplete="email" name="adminEmail" onChange={(event) => setAdminEmail(event.target.value)} required type="email" value={adminEmail} /></label>
                    <button className="primaryButton compactButton" disabled={busy !== null} type="submit">{busy === `invite-${tenant.id}` ? "正在发送…" : "发送邀请"}</button>
                    <button className="textAction" onClick={() => setInviteFor(null)} type="button">取消</button>
                  </form>
                )}
              </article>
            ))}
          </div>
        )}
        <div className="tenantPagination">
          <button className="secondaryButton" disabled={loading || offset === 0} onClick={() => void refresh(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
          <span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span>
          <button className="secondaryButton" disabled={loading || !hasNext} onClick={() => void refresh(offset + PAGE_SIZE)}>下一页</button>
        </div>
      </section>
    </div>
  );
}
