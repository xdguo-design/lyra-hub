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
