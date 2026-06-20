import axios from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const api = axios.create({ baseURL: "/api", timeout: 120000 });

export { api };

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: () => api.get("/stats").then((r) => r.data),
    refetchInterval: 30000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get("/settings").then((r) => r.data),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => api.put("/settings", data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useVerifyVk() {
  return useMutation({
    mutationFn: (data: { vk_token: string; vk_group_id: number; vk_owner_id: number }) =>
      api.post("/settings/verify-vk", data).then((r) => r.data),
  });
}

export function useUploadCookies() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post("/settings/cookies", fd).then((r) => r.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useDeleteCookies() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete("/settings/cookies").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useExtract() {
  return useMutation({
    mutationFn: (urls: string[]) => api.post("/extract", { urls }).then((r) => r.data),
  });
}

export function usePreview() {
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => api.post("/preview", data).then((r) => r.data),
  });
}

export function usePublish() {
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => api.post("/publish", data).then((r) => r.data),
  });
}

export function useTaskStatus(taskId: string | null) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.get(`/task/${taskId}`).then((r) => r.data),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "processing" || status === "pending" ? 2000 : false;
    },
  });
}

export function useScheduledPosts() {
  return useQuery({
    queryKey: ["scheduled"],
    queryFn: () => api.get("/scheduled").then((r) => r.data),
  });
}

export function useCalendar(year: number, month: number) {
  return useQuery({
    queryKey: ["calendar", year, month],
    queryFn: () => api.get(`/scheduled/calendar?year=${year}&month=${month}`).then((r) => r.data),
  });
}

export function useNoMediaPosts() {
  return useQuery({
    queryKey: ["no-media"],
    queryFn: () => api.get("/scheduled/no-media").then((r) => r.data),
  });
}

export function useDeletePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vkPostId: number) => api.delete(`/scheduled/${vkPostId}`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scheduled"] });
      qc.invalidateQueries({ queryKey: ["calendar"] });
      qc.invalidateQueries({ queryKey: ["no-media"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useUpdatePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ postId, data }: { postId: string; data: Record<string, unknown> }) =>
      api.put(`/scheduled/by-id/${postId}`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scheduled"] });
      qc.invalidateQueries({ queryKey: ["calendar"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useTelegramStatus() {
  return useQuery({
    queryKey: ["telegram-status"],
    queryFn: () => api.get("/telegram/status").then((r) => r.data),
    refetchInterval: 10000,
  });
}

export function useTelegramAuthStart() {
  return useMutation({
    mutationFn: (data: { phone: string }) =>
      api.post("/telegram/auth/start", data).then((r) => r.data),
  });
}

export function useTelegramAuthResend() {
  return useMutation({
    mutationFn: (data: { phone: string; phone_code_hash: string }) =>
      api.post("/telegram/auth/resend", data).then((r) => r.data),
  });
}

export function useTelegramAuthComplete() {
  return useMutation({
    mutationFn: (data: { code: string; phone_code_hash: string }) =>
      api.post("/telegram/auth/complete", data).then((r) => r.data),
  });
}

export function useTelegramAuthPassword() {
  return useMutation({
    mutationFn: (data: { password: string }) =>
      api.post("/telegram/auth/password", data).then((r) => r.data),
  });
}

export function useTelegramChannels() {
  return useQuery({
    queryKey: ["telegram-channels"],
    queryFn: () => api.get("/telegram/channels").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
}

export function useTelegramSelectChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { channel_id: number; channel_title: string }) =>
      api.post("/telegram/channels/select", data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["telegram-status"] });
    },
  });
}

export function useTelegramScheduled() {
  return useQuery({
    queryKey: ["telegram-scheduled"],
    queryFn: () => api.get("/telegram/scheduled").then((r) => r.data),
  });
}

export function useDeleteTelegramScheduled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (messageId: number) =>
      api.delete(`/telegram/scheduled/${messageId}`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["telegram-scheduled"] });
    },
  });
}
