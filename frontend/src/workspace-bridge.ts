export const LYRA_BRIDGE_VERSION = "1.0";

export type LyraWorkspaceContext = {
  mode: "workspace";
  appId: string;
  locale: string;
  theme: "light" | "dark";
  identity: {
    authenticated: boolean;
    user: { id: string; displayName?: string } | null;
    tenant: { id: string; name?: string } | null;
    roles: string[];
  };
  capabilities: string[];
};

export function buildEmbeddedUrl(url: string, hubOrigin: string): string {
  const target = new URL(url, window.location.href);
  target.searchParams.set("lyraHub", "1");
  target.searchParams.set("lyraHubOrigin", hubOrigin);
  return target.toString();
}

export function isAllowedBridgeOrigin(origin: string, allowedOrigins: string[]): boolean {
  return allowedOrigins.some((item) => item.replace(/\/$/, "") === origin.replace(/\/$/, ""));
}
