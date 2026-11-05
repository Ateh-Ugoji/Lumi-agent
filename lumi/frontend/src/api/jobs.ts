import { request } from "./http.ts";

export type BackgroundJobStatus = {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number | null;
  result: Record<string, any> | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export async function getJob(jobId: string): Promise<BackgroundJobStatus> {
  return request<BackgroundJobStatus>(`/jobs/${jobId}`);
}
