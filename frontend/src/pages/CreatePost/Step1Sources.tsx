import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { MediaCard, type MediaItem } from "@/components/MediaCard/MediaCard";
import { useExtract, api } from "@/api/client";
import { useToast } from "@/components/ui/use-toast";
import { Upload, Plus, Trash2, Link, X, Merge, Ungroup, Loader2 } from "lucide-react";

interface SourceItem {
  id: string;
  url: string;
  mediaItems: MediaItem[];
  alreadyUsed: boolean;
  error: string | null;
  groupId: number | null;
}

interface Step1Props {
  sources: SourceItem[];
  localFiles: File[];
  localPreviews: { file: File; url: string }[];
  onSourcesChange: (sources: SourceItem[]) => void;
  onLocalFilesChange: (files: File[], previews: { file: File; url: string }[]) => void;
  onNext: () => void;
}

let _nextGroupId = 1;

function Step1Sources({ sources, localFiles, localPreviews, onSourcesChange, onLocalFilesChange, onNext }: Step1Props) {
  const [urlInput, setUrlInput] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const extract = useExtract();
  const { addToast } = useToast();

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleAddUrls = async () => {
    const urls = urlInput.split("\n").map((u) => u.trim()).filter(Boolean);
    if (!urls.length) return;
    try {
      const result = await extract.mutateAsync(urls);
      const newSources: SourceItem[] = result.items.map((item: any) => ({
        id: item.id,
        url: item.source_url,
        mediaItems: item.media_items.map((m: any) => ({ ...m, selected: true })),
        alreadyUsed: item.already_used,
        error: item.error,
        groupId: null,
      }));
      onSourcesChange([...sources, ...newSources]);
      setUrlInput("");
      newSources.forEach((s) => {
        if (s.alreadyUsed) addToast({ title: "Дубликат", description: s.url, variant: "destructive" });
        if (s.error) addToast({ title: "Ошибка", description: `${s.url}: ${s.error}`, variant: "destructive" });
      });
    } catch {
      addToast({ title: "Ошибка", description: "Не удалось извлечь медиа", variant: "destructive" });
    }
  };

  const handleCombineSelected = () => {
    if (selectedIds.size < 2) return;
    const gid = _nextGroupId++;
    onSourcesChange(sources.map((s) => selectedIds.has(s.id) ? { ...s, groupId: gid } : s));
    setSelectedIds(new Set());
  };

  const handleUngroup = (groupId: number) => {
    onSourcesChange(sources.map((s) => s.groupId === groupId ? { ...s, groupId: null } : s));
  };

  const addFiles = async (files: File[]) => {
    const newPreviews: { file: File; url: string }[] = [];
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append("file", f);
        const resp = await api.post("/upload/media", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        newPreviews.push({ file: f, url: resp.data.url });
      } catch {
        newPreviews.push({ file: f, url: URL.createObjectURL(f) });
      }
    }
    onLocalFilesChange([...localFiles, ...files], [...localPreviews, ...newPreviews]);
  };

  const removeLocalFile = (idx: number) => {
    URL.revokeObjectURL(localPreviews[idx].url);
    onLocalFilesChange(localFiles.filter((_, i) => i !== idx), localPreviews.filter((_, i) => i !== idx));
  };

  const removeSource = (id: string) => onSourcesChange(sources.filter((s) => s.id !== id));

  const toggleMedia = (sourceId: string, mediaId: string) => {
    onSourcesChange(sources.map((s) =>
      s.id === sourceId
        ? { ...s, mediaItems: s.mediaItems.map((m) => m.id === mediaId ? { ...m, selected: !m.selected } : m) }
        : s
    ));
  };

  const totalMedia = sources.reduce((a, s) => a + s.mediaItems.filter((m) => m.selected).length, 0) + localFiles.length;
  const canProceed = sources.length > 0 || localFiles.length > 0;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold mb-1">Источники</h2>
        <p className="text-sm text-muted-foreground">Введите ссылки или загрузите файлы</p>
      </div>

      <div className="space-y-2">
        <Textarea
          placeholder="https://reddit.com/r/...\nhttps://twitter.com/...\nhttps://youtube.com/..."
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          rows={3}
        />
        <Button onClick={handleAddUrls} disabled={extract.isPending || !urlInput.trim()} size="sm">
          {extract.isPending ? <><Loader2 className="w-4 h-4 mr-1 animate-spin" />Извлечение...</> : <><Plus className="w-4 h-4 mr-1" />Добавить</>}
        </Button>
      </div>

      <div
        className="border-2 border-dashed border-border rounded-lg p-6 text-center hover:border-accent/50 transition-colors cursor-pointer"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); addFiles(Array.from(e.dataTransfer.files).filter((f) => /\.(jpg|jpeg|png|gif|webp|mp4|mov)$/i.test(f.name))); }}
        onClick={() => document.getElementById("file-input")?.click()}
      >
        <Upload className="w-6 h-6 mx-auto mb-1 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">Перетащите файлы или нажмите (jpg, png, gif, webp, mp4, mov)</p>
        <input id="file-input" type="file" multiple accept=".jpg,.jpeg,.png,.gif,.webp,.mp4,.mov" className="hidden"
          onChange={(e) => e.target.files && addFiles(Array.from(e.target.files))} />
      </div>

      {localPreviews.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {localPreviews.map((p, i) => (
            <div key={i} className="relative group w-14 h-14 rounded overflow-hidden border border-border">
              {p.file.type.startsWith("video/")
                ? <div className="w-full h-full flex items-center justify-center bg-muted"><Link className="w-5 h-5 text-muted-foreground" /></div>
                : <img src={p.url} alt="" className="w-full h-full object-cover" />}
              <button onClick={() => removeLocalFile(i)}
                className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-red-600 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                <X className="w-2.5 h-2.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {selectedIds.size >= 2 && (
        <Button variant="outline" size="sm" onClick={handleCombineSelected}>
          <Merge className="w-4 h-4 mr-1" />Объединить выбранное ({selectedIds.size})
        </Button>
      )}

      {sources.length > 0 && (
        <div className="space-y-3">
          {sources.map((s) => {
            const selCount = s.mediaItems.filter((m) => m.selected).length;
            const overLimit = selCount > 10;
            return (
              <div key={s.id} className={`bg-card border rounded-lg p-3 ${overLimit ? "border-yellow-600" : "border-border"} ${selectedIds.has(s.id) ? "ring-2 ring-accent/40" : ""}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <input type="checkbox" checked={selectedIds.has(s.id)} onChange={() => toggleSelect(s.id)} className="accent-accent flex-shrink-0" />
                    <Link className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                    <span className="text-sm text-accent truncate max-w-sm">{s.url}</span>
                    {s.alreadyUsed && <Badge variant="destructive" className="text-[10px] px-1">Дубль</Badge>}
                    {s.groupId !== null && <Badge className="text-[10px] px-1.5 bg-accent/20 text-accent border-0">Группа {s.groupId}</Badge>}
                    {overLimit && <Badge variant="destructive" className="text-[10px] px-1">{selCount}/10</Badge>}
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {s.groupId !== null && (
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => handleUngroup(s.groupId!)} title="Разгруппировать">
                        <Ungroup className="w-3.5 h-3.5" />
                      </Button>
                    )}
                    <Button variant="ghost" size="icon" className="h-6 w-6 text-red-400" onClick={() => removeSource(s.id)}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </div>
                {s.error
                  ? <p className="text-xs text-red-400 ml-6">{s.error}</p>
                  : <div className="flex flex-wrap gap-1.5 ml-6">
                      {s.mediaItems.map((m) => <MediaCard key={m.id} item={m} compact onToggle={(id) => toggleMedia(s.id, id)} />)}
                    </div>}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <span className="text-sm text-muted-foreground">{sources.length} источников, {totalMedia} медиа</span>
        <Button onClick={onNext} disabled={!canProceed}>Далее</Button>
      </div>
    </div>
  );
}

export { Step1Sources };
export type { SourceItem };
