import type React from "react";
import { useCallback, useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TrendingUp } from "lucide-react";
import { marketReviewApi } from "../api/marketReview";
import type {
  MarketReviewRegion,
  MarketReviewStatus,
} from "../api/marketReview";
import type { ParsedApiError } from "../api/error";
import { getParsedApiError } from "../api/error";
import { ApiErrorAlert, Button, Card } from "../components/common";
import { cn } from "../utils/cn";

// ============ 常量 ============

const REGION_OPTIONS: {
  value: MarketReviewRegion;
  label: string;
  desc: string;
}[] = [
  { value: "cn", label: "A股", desc: "沪深两市大盘复盘" },
  { value: "hk", label: "港股", desc: "恒生指数复盘" },
  { value: "us", label: "美股", desc: "US Market Recap" },
  { value: "both", label: "A股+美股", desc: "合并复盘报告" },
  { value: "all", label: "全部", desc: "A股+港股+美股" },
];

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_TIMES = 60; // 最多轮询 3 分钟

// ============ 辅助函数 ============

function formatDateTime(iso: string | null): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function statusLabel(status: MarketReviewStatus["status"]): string {
  switch (status) {
    case "pending":
      return "等待中";
    case "processing":
      return "生成中";
    case "completed":
      return "已完成";
    case "failed":
      return "生成失败";
    default:
      return status;
  }
}

// ============ 进度指示器 ============

const ProgressDots: React.FC = () => (
  <span className="inline-flex gap-1 items-center" aria-label="生成中">
    {[0, 1, 2].map((i) => (
      <span
        key={i}
        className="h-1.5 w-1.5 rounded-full bg-cyan animate-pulse"
        style={{ animationDelay: `${i * 200}ms` }}
      />
    ))}
  </span>
);

// ============ Markdown 渲染 ============

const MarkdownReport: React.FC<{ content: string }> = ({ content }) => (
  <div
    className="
      prose prose-invert prose-sm max-w-none
      prose-headings:text-foreground prose-headings:font-semibold
      prose-h1:text-xl prose-h2:text-lg prose-h3:text-base
      prose-p:leading-7 prose-p:text-secondary-text
      prose-strong:text-foreground
      prose-table:border-collapse prose-table:w-full
      prose-th:border prose-th:border-border/50 prose-th:px-3 prose-th:py-1.5 prose-th:text-xs prose-th:text-secondary-text prose-th:bg-elevated/50
      prose-td:border prose-td:border-border/30 prose-td:px-3 prose-td:py-1.5 prose-td:text-xs prose-td:text-secondary-text
      prose-blockquote:border-l-cyan prose-blockquote:text-secondary-text
      prose-code:text-cyan prose-code:bg-elevated/70 prose-code:px-1 prose-code:rounded prose-code:text-xs
      prose-hr:border-border/50
    "
  >
    <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
  </div>
);

// ============ 主页面 ============

const MarketReviewPage: React.FC = () => {
  const [region, setRegion] = useState<MarketReviewRegion>("cn");
  const [isRunning, setIsRunning] = useState(false);
  const [pollingTaskId, setPollingTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<MarketReviewStatus | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);

  useEffect(() => {
    document.title = "大盘复盘 - DSA";
  }, []);

  // Polling effect – runs whenever pollingTaskId changes
  useEffect(() => {
    if (!pollingTaskId) return;

    let pollCount = 0;
    let cancelled = false;
    let timerId: ReturnType<typeof setTimeout>;

    const tick = async () => {
      if (cancelled) return;
      try {
        const status = await marketReviewApi.getStatus(pollingTaskId);
        if (cancelled) return;
        setTaskStatus(status);
        if (status.status === "completed" || status.status === "failed") {
          setIsRunning(false);
          setPollingTaskId(null);
          return;
        }
      } catch (err) {
        if (cancelled) return;
        setIsRunning(false);
        setPollingTaskId(null);
        setError(getParsedApiError(err));
        return;
      }

      pollCount += 1;
      if (pollCount >= POLL_MAX_TIMES) {
        if (!cancelled) {
          setIsRunning(false);
          setPollingTaskId(null);
          setError({
            message: "轮询超时，请稍后重试",
            rawMessage: "轮询超时",
            title: "超时",
            category: "unknown",
          } as ParsedApiError);
        }
        return;
      }

      timerId = setTimeout(() => void tick(), POLL_INTERVAL_MS);
    };

    timerId = setTimeout(() => void tick(), POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearTimeout(timerId);
    };
  }, [pollingTaskId]);

  const handleRun = useCallback(async () => {
    setIsRunning(true);
    setError(null);
    setTaskStatus(null);
    setPollingTaskId(null);

    try {
      const accepted = await marketReviewApi.run(region);
      setTaskStatus({
        taskId: accepted.taskId,
        status: "pending",
        region: accepted.region,
        report: null,
        error: null,
        createdAt: accepted.createdAt,
        completedAt: null,
      });
      setPollingTaskId(accepted.taskId);
    } catch (err) {
      setIsRunning(false);
      setError(getParsedApiError(err));
    }
  }, [region]);

  const isDone = taskStatus?.status === "completed";
  const isFailed = taskStatus?.status === "failed";
  const isInProgress =
    taskStatus?.status === "pending" || taskStatus?.status === "processing";

  return (
    <div className="mx-auto min-h-full w-full max-w-5xl px-4 pb-8 pt-4 md:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <TrendingUp className="h-6 w-6 text-cyan" />
          大盘复盘
        </h1>
        <p className="mt-1 text-sm text-secondary-text">
          AI
          驱动的市场复盘分析：自动抓取指数行情、板块数据、市场新闻，生成结构化复盘报告。
        </p>
      </div>

      {/* Control Panel */}
      <Card variant="gradient" padding="md" className="mb-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-6">
          {/* Region selector */}
          <div className="flex-1">
            <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-secondary-text">
              市场区域
            </label>
            <div className="flex flex-wrap gap-2">
              {REGION_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setRegion(opt.value)}
                  disabled={isRunning}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                    region === opt.value
                      ? "border-cyan bg-cyan/10 text-cyan shadow-[0_0_8px_rgba(0,212,255,0.2)]"
                      : "border-border/60 bg-elevated/40 text-secondary-text hover:border-cyan/40 hover:text-foreground",
                    isRunning && "cursor-not-allowed opacity-50",
                  )}
                  title={opt.desc}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Run button */}
          <Button
            variant="primary"
            onClick={() => void handleRun()}
            disabled={isRunning}
            className="flex-shrink-0 gap-2"
          >
            {isRunning ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                生成中...
              </>
            ) : (
              <>
                <TrendingUp className="h-4 w-4" />
                开始复盘
              </>
            )}
          </Button>
        </div>

        {/* Status bar */}
        {taskStatus && (
          <div className="mt-4 flex items-center gap-3 rounded-lg border border-white/5 bg-elevated/50 px-3 py-2 text-xs">
            <span className="text-muted-text">任务状态：</span>
            <span
              className={cn(
                "font-semibold",
                isDone && "text-emerald-400",
                isFailed && "text-red-400",
                isInProgress && "text-cyan",
              )}
            >
              {statusLabel(taskStatus.status)}
              {isInProgress && (
                <span className="ml-1.5">
                  <ProgressDots />
                </span>
              )}
            </span>
            <span className="text-muted-text/50">·</span>
            <span className="text-muted-text">
              {REGION_OPTIONS.find((o) => o.value === taskStatus.region)
                ?.label ?? taskStatus.region}
            </span>
            {taskStatus.createdAt && (
              <>
                <span className="text-muted-text/50">·</span>
                <span className="text-muted-text">
                  {formatDateTime(taskStatus.createdAt)}
                </span>
              </>
            )}
          </div>
        )}
      </Card>

      {/* Error display */}
      {error && (
        <div className="mb-6">
          <ApiErrorAlert error={error} />
        </div>
      )}

      {/* Task failed message */}
      {isFailed && taskStatus?.error && (
        <div className="mb-6 rounded-lg border border-red-400/30 bg-red-400/5 px-4 py-3 text-sm text-red-400">
          <span className="font-semibold">生成失败：</span>
          {taskStatus.error}
        </div>
      )}

      {/* Loading placeholder */}
      {isInProgress && (
        <Card variant="default" padding="lg" className="mb-6 animate-pulse">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <ProgressDots />
              <span className="text-sm text-secondary-text">
                正在抓取行情数据与市场新闻，并调用 AI 生成复盘报告...
              </span>
            </div>
            <div className="space-y-2">
              {[100, 85, 70, 90, 60].map((w, i) => (
                <div
                  key={i}
                  className="h-3 rounded bg-elevated/60"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Report display */}
      {isDone && taskStatus?.report && (
        <Card variant="gradient" padding="lg" className="animate-fade-in">
          <div className="mb-4 flex items-center justify-between">
            <span className="label-uppercase text-muted-text">复盘报告</span>
            <button
              type="button"
              onClick={async () => {
                if (!taskStatus?.report) return;
                try {
                  await navigator.clipboard.writeText(taskStatus.report);
                } catch {
                  /* ignore */
                }
              }}
              className="rounded-lg border border-border/50 px-2.5 py-1 text-xs text-secondary-text transition-colors hover:border-cyan/40 hover:text-foreground"
              title="复制 Markdown 原文"
            >
              复制
            </button>
          </div>
          <MarkdownReport content={taskStatus.report} />
        </Card>
      )}

      {/* Empty state */}
      {!taskStatus && !error && !isRunning && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/50 bg-card/40 py-20 text-center">
          <TrendingUp className="mb-3 h-10 w-10 text-muted-text" />
          <p className="text-sm font-medium text-secondary-text">
            选择市场区域后点击「开始复盘」
          </p>
          <p className="mt-1 text-xs text-muted-text">
            AI 将抓取实时行情数据并生成结构化复盘报告
          </p>
        </div>
      )}
    </div>
  );
};

export default MarketReviewPage;
