import math

from src.data.borsdata_reports import LineItemAssembler


class StubBorsdataClient:
    def __init__(self):
        self.instrument = {"insId": 1, "reportCurrency": "USD"}
        self.metadata = [
            {"kpiId": 501, "nameEn": "EBITDA"},
            {"kpiId": 502, "nameEn": "Depreciation and Amortization"},
            {"kpiId": 503, "nameEn": "Return on Invested Capital"},
            {"kpiId": 504, "nameEn": "Gross Margin"},
            {"kpiId": 505, "nameEn": "Operating Margin"},
            {"kpiId": 506, "nameEn": "Interest Expense"},
            {"kpiId": 507, "nameEn": "Research and Development"},
        ]
        self.summary = {
            "kpis": [
                {"KpiId": 501, "values": [{"y": 2024, "p": 1, "v": 150.0}, {"y": 2023, "p": 4, "v": 140.0}]},
                {"KpiId": 502, "values": [{"y": 2024, "p": 1, "v": 30.0}, {"y": 2023, "p": 4, "v": 28.0}]},
                {"KpiId": 503, "values": [{"y": 2024, "p": 1, "v": 0.30}, {"y": 2023, "p": 4, "v": 0.28}]},
                {"KpiId": 506, "values": [{"y": 2024, "p": 1, "v": -10.0}, {"y": 2023, "p": 4, "v": -9.0}]},
                {"KpiId": 507, "values": [{"y": 2024, "p": 1, "v": 20.0}, {"y": 2023, "p": 4, "v": 18.0}]},
            ]
        }
        self.reports = {
            "reports": [
                {
                    "year": 2024,
                    "period": 1,
                    "report_End_Date": "2024-03-31",
                    "currency": "USD",
                    "revenues": 500.0,
                    "gross_Income": 200.0,
                    "operating_Income": 120.0,
                    "profit_To_Equity_Holders": 80.0,
                    "free_Cash_Flow": 90.0,
                    "cash_And_Equivalents": 50.0,
                    "current_Assets": 300.0,
                    "current_Liabilities": 150.0,
                    "total_Assets": 800.0,
                    "total_Equity": 400.0,
                    "non_Current_Liabilities": 180.0,
                    "net_Debt": 70.0,
                    "number_Of_Shares": 100.0,
                    "earnings_Per_Share": 0.8,
                    "cash_Flow_From_Operating_Activities": 130.0,
                    "cash_Flow_From_Financing_Activities": -20.0,
                    "intangible_Assets": 60.0,
                },
                {
                    "year": 2023,
                    "period": 4,
                    "report_End_Date": "2023-12-31",
                    "currency": "USD",
                    "revenues": 450.0,
                    "gross_Income": 180.0,
                    "operating_Income": 100.0,
                    "profit_To_Equity_Holders": 70.0,
                    "free_Cash_Flow": 60.0,
                    "cash_And_Equivalents": 45.0,
                    "current_Assets": 280.0,
                    "current_Liabilities": 140.0,
                    "total_Assets": 760.0,
                    "total_Equity": 380.0,
                    "non_Current_Liabilities": 170.0,
                    "net_Debt": 60.0,
                    "number_Of_Shares": 98.0,
                    "earnings_Per_Share": 0.7,
                    "cash_Flow_From_Operating_Activities": 110.0,
                    "cash_Flow_From_Financing_Activities": -15.0,
                    "intangible_Assets": 55.0,
                },
            ]
        }

    def get_instrument(self, ticker: str, *, api_key=None, force_refresh: bool = False):
        return self.instrument

    def get_kpi_metadata(self, *, api_key=None, force_refresh: bool = False):
        return self.metadata

    def get_kpi_summary(self, instrument_id: int, report_type: str, *, max_count=None, api_key=None):
        return self.summary

    def get_reports(self, instrument_id: int, report_type: str, *, max_count=None, original_currency=None, api_key=None):
        return self.reports


def test_line_item_assembler_merges_reports_and_kpis():
    client = StubBorsdataClient()
    assembler = LineItemAssembler(client)

    records = assembler.assemble(
        ticker="TEST",
        line_items=[
            "revenue",
            "gross_profit",
            "gross_margin",
            "operating_margin",
            "book_value_per_share",
            "total_debt",
            "debt_to_equity",
            "capital_expenditure",
            "return_on_invested_capital",
            "ebitda",
            "depreciation_and_amortization",
            "interest_expense",
            "research_and_development",
            "working_capital",
            "issuance_or_purchase_of_equity_shares",
        ],
        end_date="2024-03-31",
        period="annual",
        limit=2,
        api_key=None,
    )

    assert len(records) == 2

    latest = records[0]
    assert latest["ticker"] == "TEST"
    assert latest["report_period"] == "2024-03-31"
    assert latest["currency"] == "USD"
    assert latest["revenue"] == 500.0
    assert latest["gross_profit"] == 200.0
    assert math.isclose(latest["gross_margin"], 0.4)
    assert math.isclose(latest["operating_margin"], 0.24)
    assert latest["book_value_per_share"] == 4.0
    assert latest["total_debt"] == 120.0
    assert math.isclose(latest["debt_to_equity"], 0.3)
    assert latest["capital_expenditure"] == 40.0
    assert math.isclose(latest["return_on_invested_capital"], 0.30)
    assert latest["ebitda"] == 150.0
    assert latest["depreciation_and_amortization"] == 30.0
    assert latest["interest_expense"] == -10.0
    assert latest["research_and_development"] == 20.0
    assert latest["working_capital"] == 150.0
    assert latest["issuance_or_purchase_of_equity_shares"] == -20.0

    previous = records[1]
    assert previous["report_period"] == "2023-12-31"
    assert previous["revenue"] == 450.0
    assert previous["total_debt"] == 105.0
