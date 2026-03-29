# Market Review Today Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show today's market review on the web page for the currently selected region (`cn` or `hk`) when it exists in the database, and hide the report area when it does not.

**Architecture:** Add a small read-only backend endpoint that returns today's persisted market review from `market_review_history`, then update the web page to fetch today's review on initial load, region change, and after a successful generation run. Keep task polling for generation status, but render the report from the database-backed `todayReview` state instead of from task status payloads.

**Tech Stack:** FastAPI, Pydantic, React, TypeScript, Vitest, pytest

---

## File Map

- Modify: `api/v1/schemas/market_review.py`
  - Add a schema for today's market review response and restrict page region choices to `cn`/`hk` where relevant.
- Modify: `api/v1/endpoints/market_review.py`
  - Add `GET /today` that reads today's review from `MarketReviewRepository`.
- Modify: `apps/dsa-web/src/api/marketReview.ts`
  - Add `getToday(region)` and a type for today's review response.
- Modify: `apps/dsa-web/src/pages/MarketReviewPage.tsx`
  - Remove `us`/`both`/`all`, fetch today's review on load and region switch, and render report from persisted data.
- Modify: `docs/CHANGELOG.md`
  - Add one flat `[改进]` entry under `[Unreleased]`.
- Create: `tests/test_market_review_api.py`
  - Cover today's review endpoint for existing and missing same-day records.
- Create: `apps/dsa-web/src/pages/__tests__/MarketReviewPage.test.tsx`
  - Cover initial load, region switch, hidden report when missing, and successful run refresh.

## Task 1: Add The Backend `GET /today` Endpoint

**Files:**
- Create: `tests/test_market_review_api.py`
- Modify: `api/v1/schemas/market_review.py`
- Modify: `api/v1/endpoints/market_review.py`

- [ ] **Step 1: Write the failing backend tests**

```python
# tests/test_market_review_api.py
import os
import tempfile
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


@pytest.fixture
def client():
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["DATABASE_PATH"] = os.path.join(temp_dir.name, "market_review_api.db")
    Config._instance = None
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()

    app = create_app()
    client = TestClient(app)
    try:
        yield client, db
    finally:
        DatabaseManager.reset_instance()
        temp_dir.cleanup()


def test_get_today_market_review_returns_latest_same_day_record(client):
    client_obj, db = client
    db.replace_market_review_history_for_date(
        date.today(),
        [
            {
                "region": "cn",
                "report_markdown": "# 今日A股复盘",
                "overview_json": "{}",
                "news_json": "[]",
            }
        ],
    )

    response = client_obj.get("/api/v1/market-review/today", params={"region": "cn"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["region"] == "cn"
    assert payload["report"] == "# 今日A股复盘"
    assert payload["trade_date"] == date.today().isoformat()


def test_get_today_market_review_returns_null_report_when_missing(client):
    client_obj, _ = client

    response = client_obj.get("/api/v1/market-review/today", params={"region": "hk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["region"] == "hk"
    assert payload["report"] is None
    assert payload["trade_date"] is None
```

- [ ] **Step 2: Run the backend test to verify it fails**

Run: `python -m pytest tests/test_market_review_api.py -q`

Expected: FAIL because `/api/v1/market-review/today` does not exist yet.

- [ ] **Step 3: Implement the minimal schema and endpoint**

```python
# api/v1/schemas/market_review.py
TodayRegionType = Literal["cn", "hk"]


class MarketReviewTodayResponse(BaseModel):
    region: TodayRegionType
    trade_date: Optional[str] = None
    report: Optional[str] = None
    created_at: Optional[str] = None
```

```python
# api/v1/endpoints/market_review.py
from datetime import date, datetime

from src.repositories.market_review_repo import MarketReviewRepository


@router.get("/today", response_model=MarketReviewTodayResponse)
def get_today_market_review(region: Literal["cn", "hk"] = "cn") -> MarketReviewTodayResponse:
    repo = MarketReviewRepository()
    rows = repo.list_reviews(trade_date=date.today(), region=region, limit=1)
    if not rows:
        return MarketReviewTodayResponse(region=region, trade_date=None, report=None, created_at=None)

    row = rows[0]
    trade_date = row.get("trade_date")
    created_at = row.get("created_at")
    return MarketReviewTodayResponse(
        region=region,
        trade_date=trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date),
        report=row.get("report_markdown"),
        created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
    )
```

- [ ] **Step 4: Run the backend tests to verify they pass**

Run: `python -m pytest tests/test_market_review_api.py -q`

Expected: PASS

- [ ] **Step 5: Check the backend diff**

Run: `git diff -- api/v1/schemas/market_review.py api/v1/endpoints/market_review.py tests/test_market_review_api.py`

Expected: only the new response schema and read-only endpoint are added.

## Task 2: Update The Web API Layer And Market Review Page

**Files:**
- Create: `apps/dsa-web/src/pages/__tests__/MarketReviewPage.test.tsx`
- Modify: `apps/dsa-web/src/api/marketReview.ts`
- Modify: `apps/dsa-web/src/pages/MarketReviewPage.tsx`

- [ ] **Step 1: Write the failing page test**

```tsx
// apps/dsa-web/src/pages/__tests__/MarketReviewPage.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import MarketReviewPage from "../MarketReviewPage";

vi.mock("../../api/marketReview", () => ({
  marketReviewApi: {
    getToday: vi.fn(),
    run: vi.fn(),
    getStatus: vi.fn(),
  },
}));

test("loads today's cn review on first render and hides report when missing", async () => {
  marketReviewApi.getToday
    .mockResolvedValueOnce({
      region: "cn",
      tradeDate: "2026-03-29",
      report: "# 今日A股复盘",
      createdAt: "2026-03-29T15:00:00",
    })
    .mockResolvedValueOnce({
      region: "hk",
      tradeDate: null,
      report: null,
      createdAt: null,
    });

  render(<MarketReviewPage />);

  expect(await screen.findByText("今日A股复盘")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "美股" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全部" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "港股" }));

  await waitFor(() => {
    expect(screen.queryByText("今日A股复盘")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the page test to verify it fails**

Run: `cd apps/dsa-web && npm test -- src/pages/__tests__/MarketReviewPage.test.tsx`

Expected: FAIL because `getToday` and the new rendering behavior do not exist yet.

- [ ] **Step 3: Implement the minimal frontend API and page changes**

```ts
// apps/dsa-web/src/api/marketReview.ts
export type MarketReviewToday = {
  region: "cn" | "hk";
  tradeDate: string | null;
  report: string | null;
  createdAt: string | null;
};

async getToday(region: "cn" | "hk" = "cn"): Promise<MarketReviewToday> {
  const response = await apiClient.get<Record<string, unknown>>(
    "/api/v1/market-review/today",
    { params: { region } },
  );
  return toCamel<MarketReviewToday>(response.data);
}
```

```tsx
// apps/dsa-web/src/pages/MarketReviewPage.tsx
const REGION_OPTIONS = [
  { value: "cn", label: "A股", desc: "沪深两市大盘复盘" },
  { value: "hk", label: "港股", desc: "恒生指数复盘" },
] as const;

const [todayReview, setTodayReview] = useState<MarketReviewToday | null>(null);

const loadTodayReview = useCallback(async (nextRegion: "cn" | "hk") => {
  const review = await marketReviewApi.getToday(nextRegion);
  setTodayReview(review);
}, []);

useEffect(() => {
  void loadTodayReview(region);
}, [region, loadTodayReview]);

// after polling completed successfully:
if (status.status === "completed") {
  await loadTodayReview(status.region as "cn" | "hk");
}

// render report from todayReview.report, not taskStatus.report
{todayReview?.report ? <MarkdownReport content={todayReview.report} /> : null}

// empty state only when no todayReview.report and no error and not running:
// keep the control panel but do not render the old big empty placeholder
```

- [ ] **Step 4: Run the page test to verify it passes**

Run: `cd apps/dsa-web && npm test -- src/pages/__tests__/MarketReviewPage.test.tsx`

Expected: PASS

- [ ] **Step 5: Run a focused frontend quality check**

Run: `cd apps/dsa-web && npm run lint`

Expected: PASS or only pre-existing unrelated warnings.

## Task 3: Update Changelog And Verify The End-To-End Slice

**Files:**
- Modify: `docs/CHANGELOG.md`
- Reuse: `api/v1/schemas/market_review.py`
- Reuse: `api/v1/endpoints/market_review.py`
- Reuse: `apps/dsa-web/src/api/marketReview.ts`
- Reuse: `apps/dsa-web/src/pages/MarketReviewPage.tsx`
- Reuse: test files from Tasks 1-2

- [ ] **Step 1: Add the changelog entry**

```markdown
- [改进] 大盘复盘页面现在会按当前区域自动读取并展示当天已落库的复盘；若当天无该区域复盘则不显示报告内容，页面区域选项也收敛为 `A股` 与 `港股`。
```

- [ ] **Step 2: Run targeted backend verification**

Run: `python -m py_compile api/v1/schemas/market_review.py api/v1/endpoints/market_review.py tests/test_market_review_api.py`

Expected: no output

- [ ] **Step 3: Run targeted frontend verification**

Run: `cd apps/dsa-web && npm test -- src/pages/__tests__/MarketReviewPage.test.tsx && npm run build`

Expected: PASS

- [ ] **Step 4: Run the focused combined tests**

Run: `python -m pytest tests/test_market_review_api.py -q`

Expected: PASS

- [ ] **Step 5: Final diff review**

Run: `git diff -- api/v1/schemas/market_review.py api/v1/endpoints/market_review.py apps/dsa-web/src/api/marketReview.ts apps/dsa-web/src/pages/MarketReviewPage.tsx apps/dsa-web/src/pages/__tests__/MarketReviewPage.test.tsx tests/test_market_review_api.py docs/CHANGELOG.md`

Expected: only the planned endpoint, page behavior, tests, and changelog changes are present.

## Self-Review

- Spec coverage:
  - today API: covered in Task 1
  - only `cn`/`hk`: covered in Task 2
  - page shows today's persisted review when present: covered in Task 2
  - page hides report when missing: covered in Task 2
  - changelog and verification: covered in Task 3
- Placeholder scan:
  - No placeholders or undefined helper names remain.
- Type consistency:
  - Backend `TodayRegionType` and frontend `MarketReviewToday` both use `cn | hk`.
