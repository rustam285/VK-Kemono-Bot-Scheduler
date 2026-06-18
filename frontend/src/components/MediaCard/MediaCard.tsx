import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Check, X, Video, Image } from "lucide-react";

interface MediaItem {
  id: string;
  type: string;
  thumbnail_url?: string;
  original_url?: string;
  selected?: boolean;
  source_tool?: string;
}

interface MediaCardProps {
  item: MediaItem;
  onToggle: (id: string) => void;
  onRemove?: (id: string) => void;
  compact?: boolean;
}

function MediaCard({ item, onToggle, onRemove, compact }: MediaCardProps) {
  const isVideo = item.type === "video";

  return (
    <div
      className={cn(
        "relative group rounded-lg overflow-hidden border transition-all",
        item.selected
          ? "border-accent ring-2 ring-accent/30"
          : "border-border opacity-60"
      )}
    >
      <div className={cn("relative bg-muted", compact ? "w-12 h-12" : "w-full aspect-square")}>
        {item.thumbnail_url ? (
          <img
            src={item.thumbnail_url}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted-foreground">
            {isVideo ? <Video className="w-8 h-8" /> : <Image className="w-8 h-8" />}
          </div>
        )}

        {isVideo && (
          <Badge variant="video" className="absolute top-1 left-1 text-[10px] px-1.5 py-0">
            video
          </Badge>
        )}

        <button
          onClick={() => onToggle(item.id)}
          className={cn(
            "absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center transition-colors",
            item.selected
              ? "bg-accent text-white"
              : "bg-black/50 text-white/70 hover:bg-accent/80"
          )}
        >
          {item.selected && <Check className="w-3 h-3" />}
        </button>

        {onRemove && (
          <button
            onClick={() => onRemove(item.id)}
            className="absolute bottom-1 right-1 w-5 h-5 rounded-full bg-black/60 text-white/80 hover:bg-red-600 hover:text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </div>
    </div>
  );
}

export { MediaCard };
export type { MediaItem };
