import apiClient from "./index";

export type MarketReviewRegion = "cn" | "hk" | "us" | "both" | "all";
export type MarketReviewTodayRegion = "cn" | "hk";

export type MarketReviewTaskAccepted = {
  taskId: string;
  status: string;
  region: string;
  createdAt: string;
};

export type MarketReviewStatus = {
  taskId: string;
  status: "pending" | "processing" | "completed" | "failed";
  region: string;
  report: string | null;
  error: string | null;
  createdAt: string;
  completedAt: string | null;
};

export type MarketReviewToday = {
  region: MarketReviewTodayRegion;
  tradeDate: string | null;
  report: string | null;
  createdAt: string | null;
};

function toCamel<T>(obj: Record<string, unknown>): T {
  const result: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    const camel = k.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
    result[camel] = v;
  }
  return result as T;
}

export const marketReviewApi = {
  async run(
    region: MarketReviewRegion = "cn",
  ): Promise<MarketReviewTaskAccepted> {
    const response = await apiClient.post<Record<string, unknown>>(
      "/api/v1/market-review/run",
      { region },
      { validateStatus: (s) => s === 202 || s === 200 },
    );
    return toCamel<MarketReviewTaskAccepted>(response.data);
  },

  async getStatus(taskId: string): Promise<MarketReviewStatus> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/market-review/status/${taskId}`,
    );
    return toCamel<MarketReviewStatus>(response.data);
  },

  async getToday(
    region: MarketReviewTodayRegion = "cn",
  ): Promise<MarketReviewToday> {
    const response = await apiClient.get<Record<string, unknown>>(
      "/api/v1/market-review/today",
      { params: { region } },
    );
    return toCamel<MarketReviewToday>(response.data);
  },
};
