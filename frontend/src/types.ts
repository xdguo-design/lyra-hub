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
  allowed_origins: string[];
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

export type ApplicationPageItemConfig = {
  app_id: string;
  page_id: string;
  title: string;
  path: string;
  navigation_order: number;
  hidden: boolean;
  visible_roles: string[];
};

export type ServiceStatus = {
  id: string;
  name: string;
  base_url: string;
  reachable: boolean;
  detail: string | Record<string, unknown>;
};

export type CapabilityDependency = {
  application_id: string;
  application_name: string;
  capability: string;
  source: string | null;
  status: "available" | "unreachable" | "missing" | "unsupported";
};

export type CapabilityInfo = {
  name: string;
  source: string;
  mutation: boolean;
  description: string;
  reachable: boolean;
  supported: boolean;
  available: boolean;
};


export type PluginContribution = {
  widgets: Record<string, unknown>[];
  actions: Record<string, unknown>[];
  navigation: Record<string, unknown>[];
  pages: Record<string, unknown>[];
  slots: Record<string, unknown>[];
};

export type PluginSummary = {
  id: string;
  name: string;
  version: string;
  description: string;
  target_applications: string[];
  permissions: string[];
  capabilities_consumed: string[];
  contributions: PluginContribution;
  enabled: boolean;
  granted_permissions: string[];
};

export type MaintenanceServiceId = "hub" | "gateway" | "agents" | "narrative" | "print";
export type MaintenanceCheckStatus = "unknown" | "healthy" | "empty_catalog" | "unhealthy";

export type MaintenanceCheck = {
  status: MaintenanceCheckStatus;
  checked_at: string | null;
  check_name: string;
  error_code?: string | null;
  details?: Record<string, unknown>;
};

export type MaintenanceService = {
  status: MaintenanceCheckStatus;
  checked_at?: string | null;
  checks: Record<string, MaintenanceCheck>;
};

export type MaintenanceOverview = {
  schedule: {
    interval_seconds: number;
    enabled: boolean;
    next_run_at: string | null;
    last_run_at: string | null;
  } | null;
  services: Record<MaintenanceServiceId, MaintenanceService>;
  open_alerts: number;
  agents_available: boolean | null;
};

export type MaintenanceAlert = {
  id: number;
  service_id: string;
  check_name: string;
  error_code: string;
  severity: string;
  status: "open" | "acknowledged" | "resolved";
  consecutive_failures: number;
  first_occurred_at: string;
  last_occurred_at: string;
  resolved_at?: string | null;
};

export type MaintenanceCheckResult = {
  service_id: MaintenanceServiceId;
  check_name: string;
  status: MaintenanceCheckStatus;
  error_code: string | null;
  details: Record<string, unknown>;
  duration_ms: number;
  checked_at?: string;
};

export type MaintenanceRepairResult = {
  service_id: "gateway" | "agent-os";
  action: "restore_last_good";
  configuration_status: "restored";
  verification_status: "healthy" | "unhealthy";
  revision: number;
  replayed?: boolean;
};

export type AgentsTenant = {
  id: string;
  name: string;
  active: boolean;
  created_at: string;
};

export type AgentsTenantPage = {
  items: AgentsTenant[];
  total?: number;
  limit?: number;
  offset?: number;
};

export type AgentsAccessToken = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export type AgentsPrincipal = {
  id: string;
  principal_type: string;
  tenant_id: string | null;
  role: string | null;
  scopes: string[];
};

export type GovernanceRole = {
  id: string;
  name: string;
  owner: string;
  description: string;
  enabled: boolean;
  lifecycle: "active" | "archived";
  current_version: string | null;
  revision: number;
};

export type RegisteredAgent = {
  id: string;
  name: string;
  owner: string;
  description: string;
  enabled: boolean;
  lifecycle: "active" | "archived";
  current_version: string | null;
  revision: number;
};

export type TenantGatewayConfig = {
  configured: boolean;
  key_present: boolean;
  base_url: string | null;
  model: string | null;
  fingerprint?: string | null;
  updated_at?: string | null;
};

export type AgentRun = {
  run_id: string;
  tenant_id: string;
  agent_id: string;
  agent_version: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";
  output: string | null;
  output_state: string;
  model: string | null;
  usage: Record<string, unknown> | null;
  error: { code: string } | null;
};
