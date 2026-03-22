import apiClient from "./index";

export type SmartSelectColumn = {
  key: string;
  title: string;
};

export type SmartSelectRequest = {
  keywords: string;
  market_type?: "stock" | "bk" | "etf";
  qgqp_b_id?: string;
};

export type SmartSelectResponse = {
  keywords: string;
  market_type: string;
  total: number;
  columns: SmartSelectColumn[];
  stocks: Record<string, string>[];
};

export const smartSelectApi = {
  async search(params: SmartSelectRequest): Promise<SmartSelectResponse> {
    const market_type = params.market_type ?? "stock";
    const endpoint =
      market_type === "bk"
        ? "/api/v1/smart-select/bk"
        : market_type === "etf"
          ? "/api/v1/smart-select/etf"
          : "/api/v1/smart-select/stocks";

    const response = await apiClient.post<SmartSelectResponse>(endpoint, {
      keywords: params.keywords,
      market_type,
      ...(params.qgqp_b_id ? { qgqp_b_id: params.qgqp_b_id } : {}),
    });
    return response.data;
  },
};
