export type ServiceStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

export type ServiceInfo = {
  id: string;
  name: string;
  url: string;
  version: string;
  status: ServiceStatus;
};

export type Incident = {
  id: string;
  title: string;
  severity: "sev1" | "sev2" | "sev3" | "sev4";
  status: "open" | "investigating" | "remediating" | "verifying" | "closed";
  service: string;
  openedAt: string;
};

export type Deployment = {
  eventId: string;
  service: string;
  revision: string;
  status: "in_progress" | "succeeded" | "failed";
  storedAt: string;
};

