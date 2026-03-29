import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from server import app
from src.services.smart_stock_service import SmartStockService


class SmartStockServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SmartStockService(qgqp_b_id="123", timeout=5)
        self.client = TestClient(app)

    @patch("src.services.smart_stock_service.requests.post")
    def test_search_stock_treats_code_201_as_empty_result(self, mock_post: Mock):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "code": "201",
            "msg": "抱歉，未能找到符合条件的结果，您可以修改条件",
            "data": {
                "result": {
                    "columns": [
                        {"key": "SECURITY_CODE", "title": "代码"},
                        {"key": "SECURITY_SHORT_NAME", "title": "名称"},
                    ],
                    "dataList": [],
                    "count": 0,
                }
            },
        }
        mock_post.return_value = mock_response

        result = self.service.search_stock("不会命中的条件", page_size=10)

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["stocks"], [])
        self.assertEqual(
            result["columns"],
            [
                {"key": "SECURITY_CODE", "title": "代码"},
                {"key": "SECURITY_SHORT_NAME", "title": "名称"},
            ],
        )

    def test_parse_response_uses_msg_field_for_upstream_errors(self):
        with self.assertRaisesRegex(ValueError, "未能识别输入条件"):
            self.service._parse_response(
                {
                    "code": "501",
                    "msg": "抱歉，未能识别输入条件，请修改后重试",
                    "data": {"result": {"columns": [], "dataList": [], "count": 0}},
                }
            )

    @patch("src.services.smart_stock_service.requests.post")
    def test_smart_select_endpoint_returns_200_for_empty_upstream_result(
        self, mock_post: Mock
    ):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "code": "201",
            "msg": "抱歉，未能找到符合条件的结果，您可以修改条件",
            "data": {
                "result": {
                    "columns": [
                        {"key": "SECURITY_CODE", "title": "代码"},
                    ],
                    "dataList": [],
                    "count": 0,
                }
            },
        }
        mock_post.return_value = mock_response

        response = self.client.post(
            "/api/v1/smart-select/stocks",
            json={"keywords": "不会命中的条件"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "keywords": "不会命中的条件",
                "market_type": "stock",
                "total": 0,
                "columns": [{"key": "SECURITY_CODE", "title": "代码"}],
                "stocks": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
