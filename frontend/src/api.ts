import type { ApplicationSummary } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function listApplications(): Promise<ApplicationSummary[]> {
  const response = await fetch(API_BASE + "/api/v1/applications");
  if (!response.ok) {
    throw new Error("应用列表加载失败");
  }
  return response.json() as Promise<ApplicationSummary[]>;
}

export async function getHubHealth(): Promise<boolean> {
  try {
    const response = await fetch(API_BASE + "/health");
    return response.ok;
  } catch {
    return false;
  }
}
