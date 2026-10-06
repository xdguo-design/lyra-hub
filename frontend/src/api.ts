import type {
  ApplicationDetail,
  ApplicationLaunch,
  ApplicationPageConfig,
  ApplicationPageItemConfig,
  ApplicationSummary,
  AuditEvent,
  AgentsTenant,
  AgentsTenantPage,
  CapabilityDependency,
  CapabilityInfo,
  PluginSummary,
  MaintenanceAlert,
  MaintenanceCheckResult,
  MaintenanceOverview,
  MaintenanceRepairResult,
  ServiceStatus,
  AgentsAccessToken,
  AgentsPrincipal,
  GovernanceRole,
  RegisteredAgent,
  TenantGatewayConfig,
  AgentRun,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class HubApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
    this.name = "HubApiError";
  }
}

async function request<T>(path: string, init?: RequestInit, requiresPlatformAdmin = false): Promise<T> {
  const adminToken = requiresPlatformAdmin ? sessionStorage.getItem("lyra-hub-admin-token") : null;
  const response = await fetch(API_BASE + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(adminToken ? { "X-Lyra-Admin-Token": adminToken } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string | { detail?: string; code?: string } } | null;
    const detail = body?.detail;
    const code = typeof detail === "object" ? detail?.code : undefined;
    const message = typeof detail === "string" ? detail : detail?.detail ?? code ?? "请求失败";
    throw new HubApiError(message, response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getMaintenanceOverview(): Promise<{ data: MaintenanceOverview }> {
  return request("/api/v1/maintenance/overview", undefined, true);
}

export function listMaintenanceAlerts(): Promise<{ data: MaintenanceAlert[] }> {
  return request("/api/v1/maintenance/alerts?limit=500", undefined, true);
}

export function runMaintenanceChecks(): Promise<{ data: MaintenanceCheckResult[] }> {
  return request("/api/v1/maintenance/checks", { method: "POST" }, true);
}

export function acknowledgeMaintenanceAlert(alertId: number): Promise<{ data: MaintenanceAlert }> {
  return request(`/api/v1/maintenance/alerts/${alertId}/acknowledge`, { method: "POST" }, true);
}

export function confirmMaintenanceRepair(
  serviceId: "gateway" | "agent-os",
  payload: { action: "restore_last_good"; expected_revision: number; confirmed: true },
  idempotencyKey: string,
): Promise<{ data: MaintenanceRepairResult }> {
  return request(`/api/v1/maintenance/repairs/${serviceId}/confirm`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  }, true);
}

export function listAgentsTenants(limit = 50, offset = 0): Promise<AgentsTenantPage> {
  return request(`/api/v1/agents/platform/tenants?limit=${limit}&offset=${offset}`, undefined, true);
}

export function createAgentsTenant(payload: Pick<AgentsTenant, "id" | "name">): Promise<AgentsTenant> {
  return request("/api/v1/agents/platform/tenants", { method: "POST", body: JSON.stringify(payload) }, true);
}

export function setAgentsTenantActive(tenantId: string, active: boolean): Promise<Pick<AgentsTenant, "id" | "name" | "active">> {
  return request(`/api/v1/agents/platform/tenants/${encodeURIComponent(tenantId)}`, {
    method: "PATCH",
    body: JSON.stringify({ active }),
  }, true);
}

export function inviteAgentsTenantAdmin(tenantId: string, email: string): Promise<{ invitation_token: string; expires_in: number }> {
  return request(`/api/v1/agents/platform/tenants/${encodeURIComponent(tenantId)}/admins`, {
    method: "POST",
    body: JSON.stringify({ email }),
  }, true);
}

export function listApplications(): Promise<ApplicationSummary[]> {
  return request<ApplicationSummary[]>("/api/v1/applications");
}

export function listNavigation(roles?: string): Promise<ApplicationSummary[]> {
  return request<ApplicationSummary[]>("/api/v1/navigation", roles ? { headers: { "X-Lyra-Roles": roles } } : undefined);
}

export function getApplication(appId: string): Promise<ApplicationDetail> {
  return request<ApplicationDetail>("/api/v1/applications/" + encodeURIComponent(appId));
}

export function setApplicationEnabled(appId: string, enabled: boolean): Promise<ApplicationDetail> {
  return request<ApplicationDetail>("/api/v1/applications/" + encodeURIComponent(appId), {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export function launchApplication(appId: string): Promise<ApplicationLaunch> {
  return request<ApplicationLaunch>("/api/v1/applications/" + encodeURIComponent(appId) + "/launch", {
    method: "POST",
  });
}

export function listPageConfiguration(): Promise<ApplicationPageConfig[]> {
  return request<ApplicationPageConfig[]>("/api/v1/page-config");
}

export function updatePageConfiguration(
  appId: string,
  update: Partial<Omit<ApplicationPageConfig, "app_id">>,
): Promise<ApplicationPageConfig> {
  return request<ApplicationPageConfig>("/api/v1/page-config/" + encodeURIComponent(appId), {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

export function listApplicationPages(appId: string): Promise<ApplicationPageItemConfig[]> {
  return request<ApplicationPageItemConfig[]>(
    "/api/v1/page-config/" + encodeURIComponent(appId) + "/pages",
  );
}

export function updateApplicationPage(
  appId: string,
  pageId: string,
  update: Partial<Omit<ApplicationPageItemConfig, "app_id" | "page_id" | "path">>,
): Promise<ApplicationPageItemConfig> {
  return request<ApplicationPageItemConfig>(
    "/api/v1/page-config/" + encodeURIComponent(appId) + "/pages/" + encodeURIComponent(pageId),
    { method: "PATCH", body: JSON.stringify(update) },
  );
}

export function listAuditEvents(): Promise<AuditEvent[]> {
  return request<AuditEvent[]>("/api/v1/audit/events?limit=40");
}

export async function getPlatformStatus(): Promise<ServiceStatus[]> {
  const response = await request<{ services: ServiceStatus[] }>("/api/v1/platform/status");
  return response.services;
}

export async function listCapabilities(): Promise<CapabilityInfo[]> {
  const response = await request<{ data: CapabilityInfo[] }>("/api/v1/capabilities");
  return response.data;
}

export async function listCapabilityDependencies(): Promise<CapabilityDependency[]> {
  const response = await request<{ data: CapabilityDependency[] }>(
    "/api/v1/capability-dependencies",
  );
  return response.data;
}

export async function invokeCapability(
  capability: string,
  payload: Record<string, unknown> = {},
  requiresPlatformAdmin = false,
): Promise<Record<string, unknown>> {
  const response = await request<{ result: Record<string, unknown> }>(
    "/api/v1/capabilities/" + encodeURIComponent(capability) + "/invoke",
    { method: "POST", body: JSON.stringify({ payload }) },
    requiresPlatformAdmin,
  );
  return response.result;
}

export function listPlugins(applicationId?: string): Promise<PluginSummary[]> {
  const query = applicationId ? "?application_id=" + encodeURIComponent(applicationId) : "";
  return request<PluginSummary[]>("/api/v1/plugins" + query);
}

export function updatePlugin(
  pluginId: string,
  update: { enabled?: boolean; granted_permissions?: string[] },
): Promise<PluginSummary> {
  return request<PluginSummary>("/api/v1/plugins/" + encodeURIComponent(pluginId), {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

export async function getHubHealth(): Promise<boolean> {
  try {
    const response = await fetch(API_BASE + "/health");
    return response.ok;
  } catch {
    return false;
  }
}

function agentsUserRequest<T>(path: string, accessToken: string, init?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${accessToken}`,
    },
  });
}

export function agentsLogin(email: string, password: string): Promise<AgentsAccessToken> {
  return request("/api/v1/agents/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function agentsLogout(refreshToken: string): Promise<void> {
  return request("/api/v1/agents/auth/logout", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function getAgentsIdentity(accessToken: string): Promise<AgentsPrincipal> {
  return agentsUserRequest("/api/v1/agents/auth/me", accessToken);
}

export function getTenantGatewayConfig(accessToken: string): Promise<TenantGatewayConfig> {
  return agentsUserRequest("/api/v1/agents/tenants/me/gateway", accessToken);
}

export function saveTenantGatewayConfig(
  accessToken: string,
  config: { base_url: string; token: string; model: string },
): Promise<TenantGatewayConfig> {
  return agentsUserRequest("/api/v1/agents/tenants/me/gateway", accessToken, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export function checkTenantGatewayConfig(accessToken: string): Promise<{ healthy: boolean; code: string }> {
  return agentsUserRequest("/api/v1/agents/tenants/me/gateway/check", accessToken, { method: "POST" });
}

export function checkTenantGatewayDraft(
  accessToken: string,
  config: { base_url: string; token: string; model: string },
): Promise<{ healthy: boolean; code: string }> {
  return agentsUserRequest("/api/v1/agents/tenants/me/gateway/check-draft", accessToken, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function listGatewayModels(): Promise<Record<string, unknown>[]> {
  const result = await invokeCapability("model.list");
  return Array.isArray(result.data) ? result.data as Record<string, unknown>[] : [];
}

export async function listAgentRoles(accessToken: string): Promise<GovernanceRole[]> {
  const page = await agentsUserRequest<{ items: GovernanceRole[] }>(
    "/api/v1/agents/roles?limit=100&offset=0",
    accessToken,
  );
  return page.items;
}

export function createAgentRole(
  accessToken: string,
  payload: { id: string; name: string; owner: string; description: string },
): Promise<GovernanceRole> {
  return agentsUserRequest("/api/v1/agents/roles", accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listAgentRoleVersions(accessToken: string, roleId: string): Promise<Record<string, unknown>[]> {
  return agentsUserRequest<Record<string, unknown>[]>(
    `/api/v1/agents/roles/${encodeURIComponent(roleId)}/versions`, accessToken,
  );
}

export function createAgentRoleVersion(
  accessToken: string,
  roleId: string,
  payload: { version: string; responsibilities: string[]; constraints: string[]; created_by: string },
): Promise<unknown> {
  return agentsUserRequest(`/api/v1/agents/roles/${encodeURIComponent(roleId)}/versions`, accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function publishAgentRoleVersion(accessToken: string, roleId: string, version: string): Promise<GovernanceRole> {
  return agentsUserRequest(`/api/v1/agents/roles/${encodeURIComponent(roleId)}/current-version`, accessToken, {
    method: "PUT",
    body: JSON.stringify({ version }),
  });
}

export async function listRegisteredAgents(accessToken: string): Promise<RegisteredAgent[]> {
  const page = await agentsUserRequest<{ items: RegisteredAgent[] }>(
    "/api/v1/agents/agents?limit=100&offset=0",
    accessToken,
  );
  return page.items;
}

export function createRegisteredAgent(
  accessToken: string,
  payload: { id: string; name: string; owner: string; description: string },
): Promise<RegisteredAgent> {
  return agentsUserRequest("/api/v1/agents/agents", accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listRegisteredAgentVersions(accessToken: string, agentId: string): Promise<Record<string, unknown>[]> {
  return agentsUserRequest<Record<string, unknown>[]>(
    `/api/v1/agents/agents/${encodeURIComponent(agentId)}/versions`, accessToken,
  );
}

export function createRegisteredAgentVersion(
  accessToken: string,
  agentId: string,
  payload: { version: string; role_id: string; created_by: string },
): Promise<unknown> {
  return agentsUserRequest(`/api/v1/agents/agents/${encodeURIComponent(agentId)}/versions`, accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function publishRegisteredAgentVersion(
  accessToken: string,
  agentId: string,
  version: string,
): Promise<RegisteredAgent> {
  return agentsUserRequest(`/api/v1/agents/agents/${encodeURIComponent(agentId)}/current-version`, accessToken, {
    method: "PUT",
    body: JSON.stringify({ version }),
  });
}

export function runRegisteredAgent(
  accessToken: string,
  agentId: string,
  input: string,
  idempotencyKey: string,
): Promise<{ data: AgentRun }> {
  return agentsUserRequest(`/api/v1/agents/agents/${encodeURIComponent(agentId)}/runs`, accessToken, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ input }),
  });
}

export type PlatformConnection = {
  service_id: "gateway" | "agent-os";
  base_url: string;
  credential_configured: boolean;
  revision: number;
  source: "environment" | "database";
  checked_at: string | null;
  has_last_good: boolean;
};

export type PlatformConnectionCheck = {
  service_id: "gateway" | "agent-os";
  reachable: boolean;
  catalog_access: boolean;
  catalog_name?: string;
  catalog_count: number | null;
  error_code: string | null;
  detail?: string | Record<string, unknown>;
  checked_at: string;
};

export async function listPlatformConnections(): Promise<PlatformConnection[]> {
  const response = await request<{ data: PlatformConnection[] }>("/api/v1/platform/connections");
  return response.data;
}

export function checkPlatformConnection(
  serviceId: PlatformConnection["service_id"],
  draft: { base_url: string; credential?: string; clear_credential?: boolean; expected_revision: number },
): Promise<PlatformConnectionCheck> {
  return request(`/api/v1/platform/connections/${serviceId}/check`, {
    method: "POST", body: JSON.stringify(draft),
  }, true);
}

export function savePlatformConnection(
  serviceId: PlatformConnection["service_id"],
  draft: { base_url: string; credential?: string; clear_credential?: boolean; expected_revision: number },
): Promise<{ connection: PlatformConnection; check: PlatformConnectionCheck }> {
  return request(`/api/v1/platform/connections/${serviceId}`, { method: "PUT", body: JSON.stringify(draft) }, true);
}

export function restorePlatformConnection(
  serviceId: PlatformConnection["service_id"],
  expectedRevision: number,
): Promise<{ connection: PlatformConnection; revision: number }> {
  return request(`/api/v1/platform/connections/${serviceId}/restore?expected_revision=${expectedRevision}`, {
    method: "POST",
  }, true);
}

export function clearSavedPlatformConnection(
  serviceId: PlatformConnection["service_id"],
  expectedRevision: number,
): Promise<{ connection: PlatformConnection }> {
  return request(`/api/v1/platform/connections/${serviceId}?expected_revision=${expectedRevision}`, {
    method: "DELETE",
  }, true);
}
