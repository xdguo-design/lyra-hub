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
  navigation_group: string;
  enabled: boolean;
  hidden: boolean;
  visible_roles: string[];
  default_launch_mode: "workspace" | "standalone";
};

export type ApplicationDetail = ApplicationSummary & {
  capabilities_consumed: string[];
  capabilities_provided: string[];
  permissions: string[];
  health_url?: string | null;
  manifest: Record<string, unknown>;
};

export type ApplicationLaunch = {
  app_id: string;
  launch_mode: "workspace" | "standalone";
  integration_type: string;
  url: string;
  workspace_path: string;
};

export type AuditEvent = {
  id: number;
  action: string;
  target_type: string;
  target_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ApplicationPageConfig = {
  app_id: string;
  name_override?: string | null;
  navigation_group: string;
  navigation_order: number;
  hidden: boolean;
  visible_roles: string[];
  default_launch_mode: "workspace" | "standalone";
};

export type ServiceStatus = {
  id: string;
  name: string;
  base_url: string;
  reachable: boolean;
  detail: string | Record<string, unknown>;
};

export type CapabilityInfo = {
  name: string;
  source: string;
  mutation: boolean;
  description: string;
  reachable: boolean;
};
