import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { MoreHorizontal } from 'lucide-react';
import { getActionColor } from './output-tab-utils';
import type { MarketContextSnapshot, BacktestDayResult, BacktestPerformanceMetrics } from '@/services/types';

interface CompanyEventItem {
  amount?: number | null;
  category?: string;
  currency?: string | null;
  date?: string;
  description?: string | null;
  event_id?: string | number | null;
  report_type?: string | null;
  title?: string | null;
  ticker?: string | null;
}

interface InsiderTradeItem {
  filing_date?: string | null;
  issuer?: string | null;
  name?: string | null;
  shares_owned_after_transaction?: number | null;
  shares_owned_before_transaction?: number | null;
  security_title?: string | null;
  title?: string | null;
  ticker?: string | null;
  transaction_date?: string | null;
  transaction_price_per_share?: number | null;
  transaction_shares?: number | null;
  transaction_value?: number | null;
}

const hasContextEntries = (record?: Record<string, Array<Record<string, unknown>>> | null) => {
  if (!record) return false;
  return Object.values(record).some((entries) => Array.isArray(entries) && entries.length > 0);
};

const formatDate = (value?: string | null) => {
  if (!value) return '--';

  const parsedTimestamp = new Date(value);
  if (!Number.isNaN(parsedTimestamp.getTime())) {
    return parsedTimestamp.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  const fallbackTimestamp = new Date(`${value}T00:00:00Z`);
  if (!Number.isNaN(fallbackTimestamp.getTime())) {
    return fallbackTimestamp.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  return value;
};

const formatNumber = (value?: number | null, options?: Intl.NumberFormatOptions) => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '--';
  }

  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 2,
    ...options,
  }).format(value);
};

const formatEventAmount = (event: CompanyEventItem) => {
  if (event.amount === null || event.amount === undefined) {
    return null;
  }

  const amount = formatNumber(event.amount, { maximumFractionDigits: 4 });
  if (event.currency) {
    return `${amount} ${event.currency}`;
  }

  return amount;
};

const inferTradeName = (trade: InsiderTradeItem) => {
  if (trade.name && trade.name.trim().length > 0) {
    return trade.name;
  }

  if (trade.issuer && trade.issuer.trim().length > 0) {
    return trade.issuer;
  }

  return '--';
};

interface BacktestAgent {
  message?: string;
  status?: string;
  backtestResults?: BacktestDayResult[];
}

interface AgentData {
  backtest?: BacktestAgent;
}

// Component for displaying backtest progress
function BacktestProgress({ agentData }: { agentData: AgentData }) {
  const backtestAgent = agentData.backtest;
  
  if (!backtestAgent) return null;
  
  // Get the latest backtest result from the backtest results array
  const backtestResults = backtestAgent.backtestResults || [];
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Backtest Progress</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Current Status */}
          <div className="flex items-center gap-2">
            <MoreHorizontal className="h-4 w-4 text-yellow-500" />
            <span className="font-medium">Backtest Runner</span>
            <span className="text-yellow-500 flex-1">{backtestAgent.message || backtestAgent.status}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Render most recent calendar + insider context while the stream is active
function BacktestMarketContextLive({ agentData }: { agentData: AgentData }) {
  const backtestAgent = agentData.backtest;

  if (!backtestAgent || !Array.isArray(backtestAgent.backtestResults) || backtestAgent.backtestResults.length === 0) {
    return null;
  }

  const latestBacktestResult = backtestAgent.backtestResults[backtestAgent.backtestResults.length - 1];
  const snapshot: MarketContextSnapshot | undefined = latestBacktestResult?.market_context;

  if (!snapshot || (!hasContextEntries(snapshot.company_events) && !hasContextEntries(snapshot.insider_trades))) {
    return null;
  }

  const eventRows = Object.entries(snapshot.company_events ?? {}).flatMap(([ticker, events]) =>
    (events as CompanyEventItem[]).map((event, index) => ({ ticker, event, index }))
  );

  const tradeRows = Object.entries(snapshot.insider_trades ?? {}).flatMap(([ticker, trades]) =>
    (trades as InsiderTradeItem[]).map((trade, index) => ({ ticker, trade, index }))
  );

  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Latest Market Context</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h4 className="font-medium mb-2">Company Events</h4>
            {eventRows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No company events have posted yet.</p>
            ) : (
              <div className="max-h-72 overflow-y-auto pr-1">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead>Ticker</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>Details</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {eventRows.map(({ ticker, event, index }) => {
                      const amountText = formatEventAmount(event);
                      const key = `${ticker}-${event.event_id ?? event.title ?? index}`;

                      return (
                        <TableRow key={key}>
                          <TableCell>{formatDate(event.date ?? snapshot.date)}</TableCell>
                          <TableCell className="font-medium text-cyan-500">{ticker}</TableCell>
                          <TableCell>
                            <Badge
                              variant={event.category === 'dividend' ? 'success' : 'secondary'}
                              className="capitalize"
                            >
                              {event.category ?? 'event'}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="font-medium leading-tight">{event.title ?? '--'}</div>
                            {event.report_type && (
                              <div className="text-xs text-muted-foreground mt-1">
                                Report: {event.report_type}
                              </div>
                            )}
                            {amountText && (
                              <div className="text-xs text-muted-foreground mt-1">{amountText}</div>
                            )}
                            {event.description && (
                              <div className="text-xs text-muted-foreground mt-1">{event.description}</div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
          <div>
            <h4 className="font-medium mb-2">Insider Trades</h4>
            {tradeRows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No insider trades have arrived for this window.</p>
            ) : (
              <div className="max-h-72 overflow-y-auto pr-1">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead>Ticker</TableHead>
                      <TableHead>Insider</TableHead>
                      <TableHead>Shares</TableHead>
                      <TableHead>Value</TableHead>
                      <TableHead>Price</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tradeRows.map(({ ticker, trade, index }) => {
                      const key = `${ticker}-${trade.transaction_date ?? trade.filing_date ?? index}`;
                      const tradeTicker = (trade.ticker ?? ticker ?? '').toString().toUpperCase();

                      return (
                        <TableRow key={key}>
                          <TableCell>{formatDate(trade.transaction_date ?? trade.filing_date ?? snapshot.date)}</TableCell>
                          <TableCell className="font-medium text-cyan-500">{tradeTicker || ticker}</TableCell>
                          <TableCell>
                            <div className="font-medium leading-tight">{inferTradeName(trade)}</div>
                            {trade.title && (
                              <div className="text-xs text-muted-foreground">{trade.title}</div>
                            )}
                            {trade.security_title && (
                              <div className="text-xs text-muted-foreground">{trade.security_title}</div>
                            )}
                          </TableCell>
                          <TableCell>{formatNumber(trade.transaction_shares, { maximumFractionDigits: 0 })}</TableCell>
                          <TableCell>{formatNumber(trade.transaction_value)}</TableCell>
                          <TableCell>{formatNumber(trade.transaction_price_per_share)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface TickerRow {
  type: 'ticker';
  date: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  shares_owned: number;
  long_shares: number;
  short_shares: number;
  position_value: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
}

interface SummaryRow {
  type: 'summary';
  date: string;
  portfolio_value: number;
  cash: number;
  portfolio_return: number;
  total_position_value: number;
  performance_metrics: BacktestPerformanceMetrics;
}

type TableRow = TickerRow | SummaryRow;

// Component for displaying backtest trading table (similar to CLI)
function BacktestTradingTable({ agentData }: { agentData: AgentData }) {
  const backtestAgent = agentData.backtest;

  // console.log("backtestAgent", backtestAgent);
  
  if (!backtestAgent || !backtestAgent.backtestResults) {
    return null;
  }
    
  // Get the backtest results directly from the agent data
  const backtestResults = backtestAgent.backtestResults || [];
  
  if (backtestResults.length === 0) {
    return null;
  }
  
  // Build table rows similar to CLI format
  const tableRows: TableRow[] = [];
  
  backtestResults.forEach((backtestResult: BacktestDayResult) => {    
    // Add ticker rows for this period
    if (backtestResult.ticker_details) {
      backtestResult.ticker_details.forEach((ticker: Record<string, unknown>) => {
        tableRows.push({
          type: 'ticker',
          date: backtestResult.date,
          ticker: ticker.ticker,
          action: ticker.action,
          quantity: ticker.quantity,
          price: ticker.price,
          shares_owned: ticker.shares_owned,
          long_shares: ticker.long_shares,
          short_shares: ticker.short_shares,
          position_value: ticker.position_value,
          bullish_count: ticker.bullish_count,
          bearish_count: ticker.bearish_count,
          neutral_count: ticker.neutral_count,
        });
      });
    }
    
    // Add portfolio summary row for this period
    tableRows.push({
      type: 'summary',
      date: backtestResult.date,
      portfolio_value: backtestResult.portfolio_value,
      cash: backtestResult.cash,
      portfolio_return: backtestResult.portfolio_return,
      total_position_value: backtestResult.portfolio_value - backtestResult.cash,
      performance_metrics: backtestResult.performance_metrics,
    });
  });
    
  // Sort by date descending (newest first) and show only the last 50 rows to avoid performance issues
  const recentRows = tableRows
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
    .slice(0, 50);
  
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Activity</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-96 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Shares</TableHead>
                <TableHead>Position Value</TableHead>
                <TableHead>Bullish</TableHead>
                <TableHead>Bearish</TableHead>
                <TableHead>Neutral</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentRows.map((row: TableRow, idx: number) => {
                if (row.type === 'ticker') {
                  return (
                    <TableRow key={idx}>
                      <TableCell className="font-medium">{row.date}</TableCell>
                      <TableCell className="font-medium text-cyan-500">{row.ticker}</TableCell>
                      <TableCell>
                        <span className={cn("font-medium", getActionColor(row.action || ''))}>
                          {row.action?.toUpperCase() || 'HOLD'}
                        </span>
                      </TableCell>
                      <TableCell className={cn("font-medium", getActionColor(row.action || ''))}>
                        {row.quantity?.toLocaleString() || 0}
                      </TableCell>
                      <TableCell>${row.price?.toFixed(2) || '0.00'}</TableCell>
                      <TableCell>{row.shares_owned?.toLocaleString() || 0}</TableCell>
                      <TableCell className="text-primary">
                        ${row.position_value?.toLocaleString() || '0'}
                      </TableCell>
                      <TableCell className="text-green-500">{row.bullish_count || 0}</TableCell>
                      <TableCell className="text-red-500">{row.bearish_count || 0}</TableCell>
                      <TableCell className="text-blue-500">{row.neutral_count || 0}</TableCell>
                    </TableRow>
                  );
                }
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

interface BacktestOutputData {
  performance_metrics?: BacktestPerformanceMetrics;
  final_portfolio?: {
    cash: number;
    margin_used: number;
    positions: Record<string, {
      long: number;
      short: number;
      long_cost_basis: number;
      short_cost_basis: number;
    }>;
  };
  total_days?: number;
}

// Component for displaying backtest results
function BacktestResults({ outputData }: { outputData: BacktestOutputData | null }) {
  if (!outputData) {
    return null;
  }

  console.log("outputData", outputData);
  
  if (!outputData.performance_metrics) {
    return (
      <Card className="bg-transparent mb-4">
        <CardHeader>
          <CardTitle className="text-lg">Backtest Results</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-muted-foreground">
            Backtest completed. Performance metrics will appear here.
          </div>
        </CardContent>
      </Card>
    );
  }
  
  const { performance_metrics, final_portfolio, total_days } = outputData;
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Backtest Results</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {/* Performance Metrics */}
          <div className="space-y-2">
            <h4 className="font-medium">Performance Metrics</h4>
            <div className="space-y-1 text-sm">
              {performance_metrics.sharpe_ratio !== null && performance_metrics.sharpe_ratio !== undefined && (
                <div className="flex justify-between">
                  <span>Sharpe Ratio:</span>
                  <span className={cn("font-medium", performance_metrics.sharpe_ratio > 1 ? "text-green-500" : "text-red-500")}>
                    {performance_metrics.sharpe_ratio.toFixed(2)}
                  </span>
                </div>
              )}
              {performance_metrics.sortino_ratio !== null && performance_metrics.sortino_ratio !== undefined && (
                <div className="flex justify-between">
                  <span>Sortino Ratio:</span>
                  <span className={cn("font-medium", performance_metrics.sortino_ratio > 1 ? "text-green-500" : "text-red-500")}>
                    {performance_metrics.sortino_ratio.toFixed(2)}
                  </span>
                </div>
              )}
              {performance_metrics.max_drawdown !== null && performance_metrics.max_drawdown !== undefined && (
                <div className="flex justify-between">
                  <span>Max Drawdown:</span>
                  <span className="font-medium text-red-500">
                    {Math.abs(performance_metrics.max_drawdown).toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          </div>
          
          {/* Portfolio Summary */}
          <div className="space-y-2">
            <h4 className="font-medium">Portfolio Summary</h4>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span>Total Days:</span>
                <span className="font-medium">{total_days}</span>
              </div>
              <div className="flex justify-between">
                <span>Final Cash:</span>
                <span className="font-medium">${final_portfolio.cash.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span>Margin Used:</span>
                <span className="font-medium">${final_portfolio.margin_used.toLocaleString()}</span>
              </div>
            </div>
          </div>
          
          {/* Exposure Metrics */}
          <div className="space-y-2">
            <h4 className="font-medium">Exposure Metrics</h4>
            <div className="space-y-1 text-sm">
              {performance_metrics.gross_exposure !== null && performance_metrics.gross_exposure !== undefined && (
                <div className="flex justify-between">
                  <span>Gross Exposure:</span>
                  <span className="font-medium">${performance_metrics.gross_exposure.toLocaleString()}</span>
                </div>
              )}
              {performance_metrics.net_exposure !== null && performance_metrics.net_exposure !== undefined && (
                <div className="flex justify-between">
                  <span>Net Exposure:</span>
                  <span className="font-medium">${performance_metrics.net_exposure.toLocaleString()}</span>
                </div>
              )}
              {performance_metrics.long_short_ratio !== null && performance_metrics.long_short_ratio !== undefined && (
                <div className="flex justify-between">
                  <span>Long/Short Ratio:</span>
                  <span className="font-medium">
                    {performance_metrics.long_short_ratio === Infinity || performance_metrics.long_short_ratio === null ? '∞' : performance_metrics.long_short_ratio.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
        
        {/* Final Positions */}
        {final_portfolio.positions && (
          <div>
            <h4 className="font-medium mb-2">Final Positions</h4>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Long Shares</TableHead>
                  <TableHead>Short Shares</TableHead>
                  <TableHead>Long Cost Basis</TableHead>
                  <TableHead>Short Cost Basis</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(final_portfolio.positions).map(([ticker, position]: [string, { long: number; short: number; long_cost_basis: number; short_cost_basis: number }]) => (
                  <TableRow key={ticker}>
                    <TableCell className="font-medium">{ticker}</TableCell>
                    <TableCell className={cn(position.long > 0 ? "text-green-500" : "text-muted-foreground")}>
                      {position.long}
                    </TableCell>
                    <TableCell className={cn(position.short > 0 ? "text-red-500" : "text-muted-foreground")}>
                      {position.short}
                    </TableCell>
                    <TableCell>${position.long_cost_basis.toFixed(2)}</TableCell>
                    <TableCell>${position.short_cost_basis.toFixed(2)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface BacktestHistoryOutputData {
  market_context?: MarketContextSnapshot[];
}

// Summarize the historical context snapshots shipped with the completed run
function BacktestMarketContextHistory({ outputData }: { outputData: BacktestHistoryOutputData | null }) {
  const snapshots = (outputData?.market_context ?? []) as MarketContextSnapshot[];

  if (!Array.isArray(snapshots) || snapshots.length === 0) {
    return null;
  }

  const snapshotsWithSignal = snapshots.filter((snapshot) =>
    snapshot && (hasContextEntries(snapshot.company_events) || hasContextEntries(snapshot.insider_trades))
  );

  if (snapshotsWithSignal.length === 0) {
    return null;
  }

  const sortedSnapshots = [...snapshotsWithSignal].sort((a, b) => {
    const aTime = Date.parse(a.date);
    const bTime = Date.parse(b.date);

    if (!Number.isNaN(bTime) && !Number.isNaN(aTime)) {
      return bTime - aTime;
    }

    return b.date.localeCompare(a.date);
  });

  const MAX_HISTORY = 10;
  const MAX_ITEMS_PER_TICKER = 3;
  const snapshotsToRender = sortedSnapshots.slice(0, MAX_HISTORY);

  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Market Context Timeline</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4 max-h-[28rem] overflow-y-auto pr-1">
          {snapshotsToRender.map((snapshot) => {
            const eventEntries = Object.entries(snapshot.company_events ?? {});
            const tradeEntries = Object.entries(snapshot.insider_trades ?? {});
            const eventCount = eventEntries.reduce((total, [, items]) => total + items.length, 0);
            const tradeCount = tradeEntries.reduce((total, [, items]) => total + items.length, 0);

            return (
              <div
                key={snapshot.date}
                className="rounded-md border border-border/50 bg-background/60 p-3 space-y-3"
              >
                <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                  <div className="font-medium">{formatDate(snapshot.date)}</div>
                  <div className="text-xs text-muted-foreground">
                    {eventCount} event{eventCount === 1 ? '' : 's'} · {tradeCount} insider trade{tradeCount === 1 ? '' : 's'}
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h5 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Company Events
                    </h5>
                    {eventEntries.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No events recorded for this period.</p>
                    ) : (
                      <ul className="space-y-2">
                        {eventEntries.map(([ticker, items]) => {
                          const typedItems = items as CompanyEventItem[];
                          const visibleItems = typedItems.slice(0, MAX_ITEMS_PER_TICKER);
                          const remaining = typedItems.length - visibleItems.length;

                          return (
                            <li key={`${snapshot.date}-${ticker}`}
                              className="space-y-1"
                            >
                              <div className="text-xs font-medium uppercase text-muted-foreground">{ticker}</div>
                              <ul className="space-y-1">
                                {visibleItems.map((event, index) => {
                                  const amountText = formatEventAmount(event);
                                  const key = `${snapshot.date}-${ticker}-${event.event_id ?? index}`;

                                  return (
                                    <li
                                      key={key}
                                      className="rounded border border-border/40 bg-background/50 px-2 py-1"
                                    >
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-medium leading-tight">
                                          {event.title ?? event.category ?? 'Event'}
                                        </span>
                                        <Badge
                                          variant={event.category === 'dividend' ? 'success' : 'secondary'}
                                          className="capitalize"
                                        >
                                          {event.category ?? 'event'}
                                        </Badge>
                                      </div>
                                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                                        <span>{formatDate(event.date ?? snapshot.date)}</span>
                                        {amountText && <span>{amountText}</span>}
                                        {event.report_type && <span>Report: {event.report_type}</span>}
                                      </div>
                                      {event.description && (
                                        <div className="mt-1 text-xs text-muted-foreground">
                                          {event.description}
                                        </div>
                                      )}
                                    </li>
                                  );
                                })}
                              </ul>
                              {remaining > 0 && (
                                <div className="text-xs text-muted-foreground">+{remaining} more</div>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>

                  <div>
                    <h5 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Insider Trades
                    </h5>
                    {tradeEntries.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No trades recorded for this period.</p>
                    ) : (
                      <ul className="space-y-2">
                        {tradeEntries.map(([ticker, items]) => {
                          const typedTrades = items as InsiderTradeItem[];
                          const visibleTrades = typedTrades.slice(0, MAX_ITEMS_PER_TICKER);
                          const remaining = typedTrades.length - visibleTrades.length;

                          return (
                            <li key={`${snapshot.date}-${ticker}-trades`} className="space-y-1">
                              <div className="text-xs font-medium uppercase text-muted-foreground">{ticker}</div>
                              <ul className="space-y-1">
                                {visibleTrades.map((trade, index) => {
                                  const key = `${snapshot.date}-${ticker}-${trade.transaction_date ?? trade.filing_date ?? index}`;

                                  return (
                                    <li
                                      key={key}
                                      className="rounded border border-border/40 bg-background/50 px-2 py-1"
                                    >
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-medium leading-tight">
                                          {inferTradeName(trade)}
                                        </span>
                                        <span className="text-xs text-muted-foreground">
                                          {formatDate(trade.transaction_date ?? trade.filing_date ?? snapshot.date)}
                                        </span>
                                      </div>
                                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                                        <span>Shares: {formatNumber(trade.transaction_shares, { maximumFractionDigits: 0 })}</span>
                                        <span>Value: {formatNumber(trade.transaction_value)}</span>
                                        {trade.transaction_price_per_share !== undefined && trade.transaction_price_per_share !== null && (
                                          <span>Price: {formatNumber(trade.transaction_price_per_share)}</span>
                                        )}
                                      </div>
                                      {trade.title && (
                                        <div className="mt-1 text-xs text-muted-foreground">{trade.title}</div>
                                      )}
                                      {trade.security_title && (
                                        <div className="text-xs text-muted-foreground">{trade.security_title}</div>
                                      )}
                                    </li>
                                  );
                                })}
                              </ul>
                              {remaining > 0 && (
                                <div className="text-xs text-muted-foreground">+{remaining} more</div>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {snapshotsWithSignal.length > MAX_HISTORY && (
          <div className="mt-3 text-xs text-muted-foreground">
            Showing the {MAX_HISTORY} most recent context snapshots.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Component for displaying real-time backtest performance
function BacktestPerformanceMetrics({ agentData }: { agentData: AgentData }) {
  const backtestAgent = agentData.backtest;
  
  if (!backtestAgent || !backtestAgent.backtestResults) return null;
  
  // Get the backtest results directly from the agent data
  const backtestResults = backtestAgent.backtestResults || [];
  
  if (backtestResults.length === 0) return null;
  
  const firstPeriod = backtestResults[0];
  const latestPeriod = backtestResults[backtestResults.length - 1];
  
  // Calculate performance metrics
  const initialValue = firstPeriod.portfolio_value;
  const currentValue = latestPeriod.portfolio_value;
  const totalReturn = ((currentValue - initialValue) / initialValue) * 100;
  
  // Calculate win rate (periods with positive returns)
  const periodReturns = backtestResults.slice(1).map((period: BacktestDayResult, idx: number) => {
    const prevPeriod = backtestResults[idx];
    return ((period.portfolio_value - prevPeriod.portfolio_value) / prevPeriod.portfolio_value) * 100;
  });
  
  const winningPeriods = periodReturns.filter((ret: number) => ret > 0).length;
  const winRate = periodReturns.length > 0 ? (winningPeriods / periodReturns.length) * 100 : 0;
  
  // Calculate max drawdown
  let maxDrawdown = 0;
  let peak = initialValue;
  
  backtestResults.forEach((period: BacktestDayResult) => {
    if (period.portfolio_value > peak) {
      peak = period.portfolio_value;
    }
    const drawdown = ((period.portfolio_value - peak) / peak) * 100;
    if (drawdown < maxDrawdown) {
      maxDrawdown = drawdown;
    }
  });
  
  return (
    <Card className="bg-transparent mb-4">
      <CardHeader>
        <CardTitle className="text-lg">Performance</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Total Return</div>
            <div className={cn("font-sm", totalReturn >= 0 ? "text-green-500" : "text-red-500")}>
              {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Win Rate</div>
            <div className="font-sm">{winRate.toFixed(1)}%</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Max Drawdown</div>
            <div className="font-sm text-red-500">{Math.abs(maxDrawdown).toFixed(2)}%</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Periods Traded</div>
            <div className="font-sm">{backtestResults.length}</div>
          </div>
        </div>
        
        {/* Additional metrics */}
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Current Value</div>
            <div className="font-sm">${currentValue?.toLocaleString()}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Initial Value</div>
            <div className="font-sm">${initialValue?.toLocaleString()}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">P&L</div>
            <div className={cn("font-sm", totalReturn >= 0 ? "text-green-500" : "text-red-500")}>
              ${(currentValue - initialValue).toLocaleString()}
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted-foreground">Long/Short Ratio</div>
            <div className="font-sm">
              {latestPeriod.long_short_ratio === Infinity || latestPeriod.long_short_ratio === null ? '∞' : latestPeriod.long_short_ratio?.toFixed(2)}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface BacktestOutputProps {
  agentData: AgentData;
  outputData: BacktestOutputData & BacktestHistoryOutputData | null;
}

// Main component for backtest output
export function BacktestOutput({ 
  agentData, 
  outputData 
}: BacktestOutputProps) {
  return (
    <>
      <BacktestProgress agentData={agentData} />
      {agentData && <BacktestMarketContextLive agentData={agentData} />}
      {outputData && <BacktestResults outputData={outputData} />}
      {outputData && <BacktestMarketContextHistory outputData={outputData} />}
      {agentData && agentData.backtest && (
        <BacktestPerformanceMetrics agentData={agentData} />
      )}
      <BacktestTradingTable agentData={agentData} />

    </>
  );
} 
