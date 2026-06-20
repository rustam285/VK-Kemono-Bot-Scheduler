import { useScheduledPosts, useDeletePost, useUpdatePost, useSettings, api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import { X, Pencil, Trash2, ExternalLink, Check } from "lucide-react";
import { useState } from "react";

interface DayDetailProps {
  date: string;
  onClose: () => void;
}

const TYPE_VARIANT: Record<string, "art" | "fursuit" | "video"> = {
  art: "art", fursuit: "fursuit", video: "video",
};

function DayDetail({ date, onClose }: DayDetailProps) {
  const { data: posts, isLoading } = useScheduledPosts();
  const { data: settings } = useSettings();
  const deletePost = useDeletePost();
  const updatePost = useUpdatePost();
  const { addToast } = useToast();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editDate, setEditDate] = useState("");

  const groupId = settings?.vk_group_id;

  const dayPosts = (posts || []).filter((p: any) => {
    if (!p.scheduled_at) return false;
    return p.scheduled_at.startsWith(date);
  }).sort((a: any, b: any) => (a.scheduled_at || "").localeCompare(b.scheduled_at || ""));

  const handleDelete = async (post: any) => {
    try {
      if (post.vk_post_id) {
        await deletePost.mutateAsync(post.vk_post_id);
      } else if (post.id) {
        await api.delete(`/scheduled/by-id/${post.id}`);
      }
      if (post.platform === "tg" || post.platform === "both") {
        try {
          if (post.tg_channel && post.tg_message_ids) {
            const ids = typeof post.tg_message_ids === "string" ? JSON.parse(post.tg_message_ids) : post.tg_message_ids;
            for (const id of ids) {
              await api.delete(`/telegram/scheduled/${id}`);
            }
          }
        } catch {
          // TG deletion is best-effort
        }
      }
      addToast({ title: "Удалено", description: "Пост удалён", variant: "success" });
    } catch {
      addToast({ title: "Ошибка", description: "Не удалось удалить пост", variant: "destructive" });
    }
  };

  const startEdit = (post: any) => {
    setEditingId(post.id || post.vk_post_id);
    setEditText(post.post_text || "");
    setEditDate(post.scheduled_at ? post.scheduled_at.slice(0, 16) : "");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText("");
    setEditDate("");
  };

  const saveEdit = async (post: any) => {
    if (!post.id && !post.vk_post_id) {
      addToast({ title: "Ошибка", description: "Пост не имеет идентификатора", variant: "destructive" });
      return;
    }
    try {
      const originalDate = post.scheduled_at ? post.scheduled_at.slice(0, 16) : "";
      const data: Record<string, unknown> = { post_text: editText };
      if (editDate !== originalDate) {
        data.scheduled_at = editDate ? new Date(editDate).toISOString() : undefined;
      }
      await updatePost.mutateAsync({ postId: post.id, data });
      setEditingId(null);
      addToast({ title: "Сохранено", description: "Пост обновлён", variant: "success" });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "Не удалось обновить пост";
      addToast({ title: "Ошибка", description: detail, variant: "destructive" });
    }
  };

  const getVkLink = (post: any) => {
    if (groupId && post.vk_post_id) {
      return `https://vk.com/wall-${groupId}_${post.vk_post_id}`;
    }
    return `https://vk.com/wall${post.vk_post_id}`;
  };

  const displayDate = new Date(date + "T00:00:00").toLocaleDateString("ru-RU", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed top-0 right-0 bottom-0 w-full max-w-[90vw] md:w-96 md:max-w-none md:static md:top-auto md:right-auto md:bottom-auto bg-card border-l border-border z-50 md:z-auto flex flex-col overflow-hidden md:translate-x-0">
        <div className="flex items-center justify-between p-4 border-b border-border flex-shrink-0">
          <h2 className="font-semibold text-sm capitalize">{displayDate}</h2>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : dayPosts.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет постов на этот день</p>
          ) : (
            <div className="space-y-3">
              {dayPosts.map((post: any) => {
                const editKey = post.id || post.vk_post_id;
                const isEditing = editingId === editKey;
                const time = post.scheduled_at
                  ? new Date(post.scheduled_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
                  : "";

                return (
                  <div key={post.id || post.vk_post_id} className="bg-background border border-border rounded-lg p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">{time}</span>
                        <Badge variant={TYPE_VARIANT[post.post_type] || "default"} className="text-[10px]">
                          {post.post_type}
                        </Badge>
                        {post.platform && post.platform !== "vk" && (
                          <Badge variant="outline" className="text-[10px]">
                            {post.platform === "both" ? "VK + TG" : "TG"}
                            {post.tg_channel_title && ` · ${post.tg_channel_title}`}
                          </Badge>
                        )}
                      </div>
                      <div className="flex gap-1">
                        {isEditing ? (
                          <>
                            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => saveEdit(post)}>
                              <Check className="w-3.5 h-3.5 text-green-400" />
                            </Button>
                            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={cancelEdit}>
                              <X className="w-3.5 h-3.5" />
                            </Button>
                          </>
                        ) : (
                          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => startEdit(post)}>
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6 text-red-400" onClick={() => handleDelete(post)}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>

                    {post.media_attachments && post.media_attachments.length > 0 && (
                      <div className="flex gap-1">
                        {post.media_attachments.slice(0, 4).map((m: any, i: number) => (
                          <div key={i} className="w-12 h-12 rounded bg-muted flex items-center justify-center text-[10px] text-muted-foreground">
                            {m.type}
                          </div>
                        ))}
                      </div>
                    )}

                    {isEditing ? (
                      <div className="space-y-2">
                        <Input
                          type="datetime-local"
                          value={editDate}
                          onChange={(e) => setEditDate(e.target.value)}
                          className="text-xs h-8"
                        />
                        <Textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          rows={3}
                          className="text-xs"
                        />
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground line-clamp-3">{post.post_text}</p>
                    )}

                    {post.vk_post_id && (
                      <a
                        href={getVkLink(post)}
                        target="_blank"
                        rel="noopener"
                        className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                      >
                        <ExternalLink className="w-3 h-3" />
                        VK
                      </a>
                    )}
                    {!post.vk_post_id && post.platform === "tg" && (
                      <span className="text-xs text-muted-foreground">Telegram (запланировано)</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export { DayDetail };
