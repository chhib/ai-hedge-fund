import math

from src.data.borsdata_kpis import FinancialMetricsAssembler


class StubBorsdataClient:
    def __init__(self):
        self.instrument = {"insId": 1, "reportCurrency": "USD"}
        self.metadata = [
            {"kpiId": 101, "nameEn": "Market Cap"},
            {"kpiId": 102, "nameEn": "Enterprise Value"},
            {"kpiId": 103, "nameEn": "P/E"},
            {"kpiId": 104, "nameEn": "Return on Equity"},
            {"kpiId": 105, "nameEn": "Inventory Turnover"},
            {"kpiId": 106, "nameEn": "Days Sales Outstanding"},
            {"kpiId": 107, "nameEn": "Operating Margin"},
            {"kpiId": 108, "nameEn": "Gross Margin"},
            {"kpiId": 109, "nameEn": "Free Cash Flow Yield"},
            {"kpiId": 111, "nameEn": "Earnings per Share"},
            {"kpiId": 112, "nameEn": "Free Cash Flow per Share"},
            {"kpiId": 210, "nameEn": "Sales Growth"},
        ]
        self.summary = {
            "kpis": [
                {"KpiId": 101, "values": [{"y": 2024, "p": 1, "v": None}, {"y": 2023, "p": 4, "v": None}]},
                {"KpiId": 102, "values": [{"y": 2024, "p": 1, "v": 950.0}, {"y": 2023, "p": 4, "v": 900.0}]},
                {"KpiId": 103, "values": [{"y": 2024, "p": 1, "v": 18.5}, {"y": 2023, "p": 4, "v": 20.1}]},
                {"KpiId": 104, "values": [{"y": 2024, "p": 1, "v": 1.2}, {"y": 2023, "p": 4, "v": 1.1}]},
                {"KpiId": 105, "values": [{"y": 2024, "p": 1, "v": 10.0}, {"y": 2023, "p": 4, "v": 8.0}]},
                {"KpiId": 106, "values": [{"y": 2024, "p": 1, "v": 30.0}, {"y": 2023, "p": 4, "v": 35.0}]},
                {"KpiId": 107, "values": [{"y": 2024, "p": 1, "v": 0.25}, {"y": 2023, "p": 4, "v": 0.22}]},
                {"KpiId": 108, "values": [{"y": 2024, "p": 1, "v": 0.5}, {"y": 2023, "p": 4, "v": 0.48}]},
                {"KpiId": 109, "values": [{"y": 2024, "p": 1, "v": 0.04}, {"y": 2023, "p": 4, "v": 0.035}]},
                {"KpiId": 111, "values": [{"y": 2024, "p": 1, "v": 5.5}, {"y": 2023, "p": 4, "v": 5.0}]},
                {"KpiId": 112, "values": [{"y": 2024, "p": 1, "v": 4.5}, {"y": 2023, "p": 4, "v": 4.0}]},
            ]
        }
        self.reports = {
            "reports": [
                {
                    "year": 2024,
                    "period": 1,
                    "report_End_Date": "2024-03-31",
                    "currency": "USD",
                    "number_Of_Shares": 10.0,
                    "stock_Price_Average": 110.0,
                    "cash_Flow_From_Operating_Activities": 200.0,
                    "current_Liabilities": 50.0,
                },
                {
                    "year": 2023,
                    "period": 4,
                    "report_End_Date": "2023-12-31",
                    "currency": "USD",
                    "number_Of_Shares": 9.0,
                    "stock_Price_Average": 90.0,
                    "cash_Flow_From_Operating_Activities": 150.0,
                    "current_Liabilities": 60.0,
                },
            ]
        }
        self.screener = {(210, "1year", "percent"): {"value": {"n": 12.5}}}

    def get_instrument(self, ticker: str, *, api_key=None, force_refresh: bool = False):
        return self.instrument

    def get_kpi_metadata(self, *, api_key=None, force_refresh: bool = False):
        return self.metadata

    def get_kpi_summary(self, instrument_id: int, report_type: str, *, max_count=None, api_key=None):
        return self.summary

    def get_reports(self, instrument_id: int, report_type: str, *, max_count=None, original_currency=None, api_key=None):
        return self.reports

    def get_kpi_screener_value(self, instrument_id: int, kpi_id: int, calc_group: str, calc: str, *, api_key=None):
        return self.screener.get((kpi_id, calc_group, calc), {})


def test_financial_metrics_assembler_builds_metrics_from_summary_and_reports():
    client = StubBorsdataClient()
    assembler = FinancialMetricsAssembler(client)

    metrics = assembler.assemble(
        ticker="TEST",
        end_date="2024-03-31",
        period="ttm",
        limit=2,
        api_key=None,
    )

    assert len(metrics) == 2

    latest = metrics[0]
    assert latest.ticker == "TEST"
    assert latest.currency == "USD"
    assert latest.period == "ttm"
    assert latest.report_period == "2024-03-31"

    assert latest.market_cap == 1100.0
    assert latest.enterprise_value == 950.0
    assert latest.price_to_earnings_ratio == 18.5
    assert latest.return_on_equity == 1.2
    assert math.isclose(latest.operating_cash_flow_ratio, 4.0)
    expected_operating_cycle = 30.0 + (365.0 / 10.0)
    assert math.isclose(latest.operating_cycle, expected_operating_cycle)
    assert math.isclose(latest.revenue_growth, 0.125)
    assert latest.earnings_per_share == 5.5
    assert latest.free_cash_flow_per_share == 4.5

    previous = metrics[1]
    assert previous.report_period == "2023-12-31"
    assert previous.market_cap == 810.0
    assert math.isclose(previous.operating_cash_flow_ratio, 2.5)
    expected_previous_cycle = 35.0 + (365.0 / 8.0)
    assert math.isclose(previous.operating_cycle, expected_previous_cycle)


def test_financial_metrics_assembler_uses_period_specific_screener_group_when_available():
    client = StubBorsdataClient()
    client.screener = {
        (210, "quarter", "percent"): {"value": {"n": 3.5}},
    }
    assembler = FinancialMetricsAssembler(client)

    metrics = assembler.assemble(
        ticker="TEST",
        end_date="2024-03-31",
        period="quarter",
        limit=1,
        api_key=None,
    )

    assert len(metrics) == 1
    assert math.isclose(metrics[0].revenue_growth, 0.035)
