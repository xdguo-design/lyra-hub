import type { ApplicationDetail, ApplicationLaunch, ApplicationSummary, AuditEvent } from "./types";

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

export function listAuditEvents(): Promise<AuditEvent[]> {
  return request<AuditEvent[]>("/api/v1/audit/events?limit=20");
}

export async function getHubHealth(): Promise<boolean> {
  try {
    const response = await fetch(API_BASE + "/health");
    return response.ok;
  } catch {
    return false;
  }
}
