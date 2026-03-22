import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { smartSelectApi } from "../api/smartSelect";
import type {
  SmartSelectColumn,
  SmartSelectResponse,
} from "../api/smartSelect";
import type { ParsedApiError } from "../api/error";
import { getParsedApiError } from "../api/error";
import { ApiErrorAlert, Button, Card, Badge } from "../components/common";
import { cn } from "../utils/cn";

// ============ 常量 ============

const DEFAULT_KEYWORDS = "MA5MA10多头排列;非ST;市值大于100亿";

const MARKET_TYPE_OPTIONS: { value: "stock" | "bk" | "etf"; label: string }[] =
  [
    { value: "stock", label: "个股" },
    { value: "bk", label: "板块" },
    { value: "etf", label: "ETF" },
  ];

const EXAMPLE_CONDITIONS = [
  "MA5MA10多头排列;非ST;市值大于100亿",
  "量比大于2，非ST，换手率大于3%",
  "今日涨幅大于3%;MACD金叉;市值50亿到300亿",
  "今日涨幅前15的ETF",
  "连续3日上涨;非ST;量比大于1.5",
];

// ============ 辅助组件 ============

const TableCell: React.FC<{ value: string; colKey: string }> = ({
  value,
  colKey,
}) => {
  if (!value || value === "")
    return <span className="text-muted-text">--</span>;

  // 涨跌幅着色（f3 通常是涨跌幅）
  if (colKey === "f3" || colKey === "f20") {
    const num = parseFloat(value);
    if (!isNaN(num)) {
      return (
        <span
          className={cn(
            "font-mono font-semibold",
            num > 0
              ? "text-red-400"
              : num < 0
                ? "text-emerald-400"
                : "text-secondary-text",
          )}
        >
          {num > 0 ? "+" : ""}
          {value}%
        </span>
      );
    }
  }

  // 代码列加粗
  if (colKey === "f12") {
    return <span className="font-mono font-semibold text-cyan">{value}</span>;
  }

  return <span>{value}</span>;
};

// ============ 主页面 ============

const SmartSelectPage: React.FC = () => {
  const [keywords, setKeywords] = useState(DEFAULT_KEYWORDS);
  const [marketType, setMarketType] = useState<"stock" | "bk" | "etf">("stock");
  const [isSearching, setIsSearching] = useState(false);
  const [result, setResult] = useState<SmartSelectResponse | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    document.title = "智能选股 - DSA";
  }, []);

  const handleSearch = useCallback(async () => {
    const trimmed = keywords.trim();
    if (!trimmed) return;

    setIsSearching(true);
    setError(null);
    setResult(null);

    try {
      const data = await smartSelectApi.search({
        keywords: trimmed,
        market_type: marketType,
      });
      setResult(data);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setIsSearching(false);
    }
  }, [keywords, marketType]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSearch();
    }
  };

  const handleExampleClick = (example: string) => {
    setKeywords(example);
    textareaRef.current?.focus();
  };

  const columns: SmartSelectColumn[] = result?.columns ?? [];
  const stocks = result?.stocks ?? [];

  return (
    <div className="flex flex-col gap-5 pb-8">
      {/* 页头 */}
      <div>
        <h1 className="text-xl font-bold text-foreground">智能选股</h1>
        <p className="mt-1 text-sm text-secondary-text">
          输入自然语言选股条件，从东方财富实时筛选符合条件的股票
        </p>
      </div>

      {/* 搜索卡片 */}
      <Card variant="gradient" padding="md">
        <div className="flex flex-col gap-4">
          {/* 市场类型 */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-secondary-text shrink-0">
              市场类型：
            </span>
            <div className="flex gap-2">
              {MARKET_TYPE_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMarketType(value)}
                  className={cn(
                    "h-7 rounded-lg px-3 text-xs font-medium transition-all",
                    marketType === value
                      ? "border border-cyan/40 bg-cyan/10 text-cyan"
                      : "border border-border/50 bg-card/50 text-secondary-text hover:bg-hover hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* 输入框 */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-secondary-text">选股条件</label>
            <div className="relative">
              <textarea
                ref={textareaRef}
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入自然语言选股条件，例如：MA5MA10多头排列;非ST;市值大于100亿"
                rows={3}
                className={cn(
                  "w-full resize-none rounded-xl border border-border/60 bg-input/60 px-4 py-3 text-sm text-foreground",
                  "placeholder:text-muted-text/70",
                  "focus:border-cyan/50 focus:outline-none focus:ring-2 focus:ring-cyan/15",
                  "transition-colors",
                )}
              />
              <div className="absolute bottom-2.5 right-3 text-[10px] text-muted-text/50 select-none">
                Ctrl+Enter 搜索
              </div>
            </div>
          </div>

          {/* 操作 */}
          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              size="md"
              onClick={() => void handleSearch()}
              isLoading={isSearching}
              loadingText="筛选中..."
              disabled={!keywords.trim() || isSearching}
            >
              <Search className="h-4 w-4" />
              开始筛选
            </Button>
            {result && !isSearching && (
              <span className="text-sm text-secondary-text">
                共找到{" "}
                <span className="font-semibold text-cyan">{result.total}</span>{" "}
                个结果，显示{" "}
                <span className="font-semibold text-foreground">
                  {stocks.length}
                </span>{" "}
                条
              </span>
            )}
          </div>

          {/* 示例条件 */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-text shrink-0">示例：</span>
            {EXAMPLE_CONDITIONS.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => handleExampleClick(example)}
                className="rounded-lg border border-border/40 bg-card/40 px-2.5 py-1 text-xs text-secondary-text transition-colors hover:border-cyan/30 hover:bg-cyan/5 hover:text-cyan"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      </Card>

      {/* 错误 */}
      {error && (
        <div className="animate-fade-in">
          <ApiErrorAlert error={error} />
        </div>
      )}

      {/* 结果表格 */}
      {result && columns.length > 0 && (
        <Card padding="none" className="animate-fade-in overflow-hidden">
          <div className="flex items-center justify-between border-b border-border/40 px-5 py-3">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-foreground">
                筛选结果
              </span>
              <Badge variant="default">
                {result.market_type === "stock"
                  ? "个股"
                  : result.market_type === "bk"
                    ? "板块"
                    : "ETF"}
              </Badge>
            </div>
            <span className="text-xs text-muted-text font-mono">
              {result.keywords}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 bg-elevated/50">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-text">
                    #
                  </th>
                  {columns.map((col) => (
                    <th
                      key={col.key}
                      className="px-4 py-2.5 text-left text-xs font-medium text-muted-text whitespace-nowrap"
                    >
                      {col.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stocks.length === 0 ? (
                  <tr>
                    <td
                      colSpan={columns.length + 1}
                      className="px-4 py-8 text-center text-sm text-muted-text"
                    >
                      未找到符合条件的结果
                    </td>
                  </tr>
                ) : (
                  stocks.map((stock, idx) => (
                    <tr
                      key={`${stock["f12"] ?? ""}-${idx}`}
                      className="border-b border-border/20 transition-colors hover:bg-hover/40"
                    >
                      <td className="px-4 py-2 text-xs text-muted-text font-mono">
                        {idx + 1}
                      </td>
                      {columns.map((col) => (
                        <td
                          key={col.key}
                          className="px-4 py-2 whitespace-nowrap"
                        >
                          <TableCell
                            value={stock[col.key] ?? ""}
                            colKey={col.key}
                          />
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* 空状态 */}
      {!result && !isSearching && !error && (
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-border/40 bg-card/60">
            <Search className="h-7 w-7 text-muted-text/60" />
          </div>
          <p className="text-sm text-muted-text">
            输入选股条件，点击「开始筛选」查看结果
          </p>
        </div>
      )}
    </div>
  );
};

export default SmartSelectPage;
