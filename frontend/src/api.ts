import type {
  ApplicationDetail,
  ApplicationLaunch,
  ApplicationPageConfig,
  ApplicationSummary,
  AuditEvent,
  CapabilityInfo,
  PluginSummary,
  ServiceStatus,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? "请求失败");
  }
  return response.json() as Promise<T>;
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

export async function invokeCapability(
  capability: string,
  payload: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const response = await request<{ result: Record<string, unknown> }>(
    "/api/v1/capabilities/" + encodeURIComponent(capability) + "/invoke",
    { method: "POST", body: JSON.stringify({ payload }) },
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
