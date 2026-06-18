import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { PostCard } from "@/components/PostCard/PostCard";
import { usePublish, useTaskStatus } from "@/api/client";
import { useToast } from "@/components/ui/use-toast";
import { Loader2, CheckCircle, XCircle, ArrowLeft } from "lucide-react";

interface PreviewPost {
  id: string;
  post_type: string;
  scheduled_at: string;
  media_items: { id: string; type: string; thumbnail_url?: string; original_url?: string; selected?: boolean }[];
  post_text: string;
  source_urls: string[];
}

interface Step3Props {
  posts: PreviewPost[];
  onPostsChange: (posts: PreviewPost[]) => void;
  onBack: () => void;
  onDone: () => void;
}

function Step3Preview({ posts, onPostsChange, onBack, onDone }: Step3Props) {
  const publish = usePublish();
  const { addToast } = useToast();
  const [taskId, setTaskId] = useState<string | null>(null);
  const taskStatus = useTaskStatus(taskId);

  const handlePublish = async () => {
    try {
      const result = await publish.mutateAsync({ posts });
      setTaskId(result.task_id);
      addToast({ title: "Публикация начата", description: `Задача: ${result.task_id}`, variant: "success" });
    } catch {
      addToast({ title: "Ошибка", description: "Не удалось начать публикацию", variant: "destructive" });
    }
  };

  const updatePost = useCallback(
    (id: string, changes: Record<string, unknown>) => {
      onPostsChange(posts.map((p) => (p.id === id ? { ...p, ...changes } : p)));
    },
    [posts, onPostsChange]
  );

  const removePost = useCallback(
    (id: string) => {
      onPostsChange(posts.filter((p) => p.id !== id));
    },
    [posts, onPostsChange]
  );

  const moveUp = useCallback(
    (id: string) => {
      const idx = posts.findIndex((p) => p.id === id);
      if (idx <= 0) return;
      const arr = [...posts];
      [arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]];
      onPostsChange(arr);
    },
    [posts, onPostsChange]
  );

  const moveDown = useCallback(
    (id: string) => {
      const idx = posts.findIndex((p) => p.id === id);
      if (idx >= posts.length - 1) return;
      const arr = [...posts];
      [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
      onPostsChange(arr);
    },
    [posts, onPostsChange]
  );

  const status = taskStatus.data?.status;
  const isRunning = status === "processing" || status === "pending";
  const isDone = status === "completed";
  const isError = status === "error";

  const successCount = taskStatus.data?.results?.filter((r: any) => r.status === "ok").length || 0;
  const errorCount = taskStatus.data?.results?.filter((r: any) => r.status === "error").length || 0;
  const progress = taskStatus.data?.progress;

  if (isDone || isError) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          {isDone ? (
            <CheckCircle className="w-16 h-16 mx-auto text-green-500 mb-4" />
          ) : (
            <XCircle className="w-16 h-16 mx-auto text-red-500 mb-4" />
          )}
          <h2 className="text-2xl font-bold mb-2">
            {isDone ? "Публикация завершена" : "Ошибка публикации"}
          </h2>
          <div className="flex justify-center gap-6 text-sm">
            <div>
              <span className="text-green-400 font-semibold text-lg">{successCount}</span>
              <p className="text-muted-foreground">Опубликовано</p>
            </div>
            {errorCount > 0 && (
              <div>
                <span className="text-red-400 font-semibold text-lg">{errorCount}</span>
                <p className="text-muted-foreground">Ошибок</p>
              </div>
            )}
          </div>
        </div>

        {taskStatus.data?.results && (
          <div className="space-y-2">
            {taskStatus.data.results.map((r: any, i: number) => (
              <div
                key={i}
                className={`flex items-center justify-between p-3 rounded-lg border ${
                  r.status === "ok" ? "border-green-800 bg-green-950/30" : "border-red-800 bg-red-950/30"
                }`}
              >
                <span className="text-sm">Пост {i + 1}</span>
                {r.status === "ok" ? (
                  <a
                    href={`https://vk.com/wall-${taskStatus.data?.results?.[0]?.vk_post_id ? "" : ""}${r.vk_post_id}`}
                    target="_blank"
                    className="text-sm text-accent hover:underline"
                  >
                    VK: {r.vk_post_id}
                  </a>
                ) : (
                  <span className="text-sm text-red-400">{r.error}</span>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-center">
          <Button onClick={onDone}>Готово</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Предпросмотр</h2>
        <p className="text-sm text-muted-foreground">
          Проверьте посты перед публикацией. Можно редактировать текст и порядок.
        </p>
      </div>

      <div className="space-y-4">
        {posts.map((post, i) => (
          <PostCard
            key={post.id}
            post={post}
            index={i}
            total={posts.length}
            onUpdate={updatePost}
            onRemove={removePost}
            onMoveUp={moveUp}
            onMoveDown={moveDown}
          />
        ))}
      </div>

      {isRunning && progress && (
        <div className="bg-muted/50 rounded-lg p-4">
          <div className="flex items-center gap-3 mb-2">
            <Loader2 className="w-4 h-4 animate-spin text-accent" />
            <span className="text-sm font-medium">
              {progress.stage === "downloading_media" && "Загрузка медиа..."}
              {progress.stage === "uploading_media" && "Загрузка в VK..."}
              {progress.stage === "creating_posts" && "Создание постов..."}
            </span>
          </div>
          <div className="w-full bg-background rounded-full h-2">
            <div
              className="bg-accent h-2 rounded-full transition-all duration-300"
              style={{ width: `${(progress.current / progress.total) * 100}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {progress.current} / {progress.total}
          </p>
        </div>
      )}

      <div className="flex justify-between">
        <Button variant="outline" onClick={onBack} disabled={isRunning}>
          <ArrowLeft className="w-4 h-4 mr-1" /> Назад
        </Button>
        <Button onClick={handlePublish} disabled={isRunning || posts.length === 0}>
          {isRunning ? (
            <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Публикация...</>
          ) : (
            `Опубликовать (${posts.length})`
          )}
        </Button>
      </div>
    </div>
  );
}

export { Step3Preview };
