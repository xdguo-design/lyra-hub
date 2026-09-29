export type ApplicationSummary = {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  icon?: string | null;
  standalone_url: string;
  workspace_path: string;
  integration_type: string;
  navigation_order: number;
  enabled: boolean;
};

export type ApplicationDetail = ApplicationSummary & {
  capabilities_consumed: string[];
  capabilities_provided: string[];
  permissions: string[];
  manifest: Record<string, unknown>;
};

export type ApplicationLaunch = {
  app_id: string;
  mode: string;
  url: string;
};

export type AuditEvent = {
  id: number;
  action: string;
  target_type: string;
  target_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};
