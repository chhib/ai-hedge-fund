import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { OutputNodeData } from '@/contexts/node-context';
import { extractBaseAgentKey } from '@/data/node-mappings';
import { createAgentDisplayNames } from '@/utils/text-utils';
import { ArrowDown, ArrowUp, Minus } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

type BadgeVariant = NonNullable<BadgeProps['variant']>;

interface InvestmentDecision {
  action?: string;
  quantity?: number;
  confidence?: number;
}

interface AnalystSignalDetail {
  signal: string;
  confidence: number;
  reasoning?: unknown;
}

type AnalystSignalsByAgent = Record<string, Record<string, AnalystSignalDetail>>;
type DecisionsByTicker = Record<string, InvestmentDecision>;

interface InvestmentReportDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  outputNodeData: OutputNodeData | null;
  connectedAgentIds: Set<string>;
}

type ActionType = 'long' | 'short' | 'hold';

const toActionType = (action?: string): ActionType => {
  if (action === 'long' || action === 'short' || action === 'hold') {
    return action;
  }
  return 'hold';
};

export function InvestmentReportDialog({
  isOpen,
  onOpenChange,
  outputNodeData,
  connectedAgentIds,
}: InvestmentReportDialogProps) {
  // Check if this is a backtest result and return early if it is
  // Backtest results should be displayed in the backtest output tab, not in the investment report dialog
  if (outputNodeData?.decisions?.backtest?.type === 'backtest_complete') {
    return null;
  }

  // Return early if no output data
  if (!outputNodeData || !outputNodeData.decisions) {
    return null;
  }

  const decisions = outputNodeData.decisions as DecisionsByTicker;
  const analystSignals = (outputNodeData.analyst_signals ?? {}) as AnalystSignalsByAgent;
  const currentPrices =
    'current_prices' in outputNodeData
      ? ((outputNodeData as OutputNodeData & { current_prices?: Record<string, number | string> })
          .current_prices ?? {})
      : {};

  const getActionIcon = (action: ActionType) => {
    switch (action) {
      case 'long':
        return <ArrowUp className="h-4 w-4 text-green-500" />;
      case 'short':
        return <ArrowDown className="h-4 w-4 text-red-500" />;
      case 'hold':
        return <Minus className="h-4 w-4 text-yellow-500" />;
      default:
        return null;
    }
  };

  const getSignalBadge = (signal: string) => {
    const variant: BadgeVariant = signal === 'bullish'
      ? 'success'
      : signal === 'bearish'
        ? 'destructive'
        : 'outline';

    return <Badge variant={variant}>{signal}</Badge>;
  };

  const getConfidenceBadge = (confidence: number) => {
    let variant: BadgeVariant = 'outline';
    if (confidence >= 50) variant = 'success';
    else if (confidence >= 0) variant = 'warning';
    const rounded = Number(confidence.toFixed(1));
    return <Badge variant={variant}>{rounded}%</Badge>;
  };

  // Extract unique tickers from the data
  const tickers = Object.keys(decisions);

  // Use the unique node IDs directly since they're now stored as keys in analyst_signals
  const connectedUniqueAgentIds = Array.from(connectedAgentIds);
  const agents = Object.keys(analystSignals)
    .filter(agent =>
      extractBaseAgentKey(agent) !== 'risk_management_agent' && connectedUniqueAgentIds.includes(agent)
    );

  const agentDisplayNames = createAgentDisplayNames(agents);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">Investment Report</DialogTitle>
        </DialogHeader>

        <div className="space-y-8 my-4">
          {/* Summary Section */}
          <section>
            <h2 className="text-lg font-semibold mb-4">Summary</h2>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>
                  Recommended trading actions based on analyst signals
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Ticker</TableHead>
                      <TableHead>Price</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead>Quantity</TableHead>
                      <TableHead>Confidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tickers.map(ticker => {
                      const decision = decisions[ticker];
                      if (!decision) return null;
                      const currentPrice = currentPrices[ticker] ?? 'N/A';
                      const action = toActionType(decision.action);
                      return (
                        <TableRow key={ticker}>
                          <TableCell className="font-medium">{ticker}</TableCell>
                          <TableCell>${typeof currentPrice === 'number' ? currentPrice.toFixed(2) : currentPrice}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              {getActionIcon(action)}
                              <span className="capitalize">{decision.action}</span>
                            </div>
                          </TableCell>
                          <TableCell>{decision.quantity}</TableCell>
                          <TableCell>{getConfidenceBadge(decision.confidence ?? 0)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </section>
          {/* Analyst Signals Section */}
          <section>
            <h2 className="text-lg font-semibold mb-4">Analyst Signals</h2>
            <Accordion type="multiple" className="w-full">
              {tickers.map(ticker => (
                <AccordionItem key={ticker} value={ticker}>
                  <AccordionTrigger className="text-base font-medium px-4 py-3 bg-muted/30 rounded-md hover:bg-muted/50">
                    <div className="flex items-center gap-2">
                      {ticker}
                      <div className="flex items-center gap-1">
                        {getActionIcon(toActionType(decisions[ticker]?.action))}
                        <span className="text-sm font-normal text-muted-foreground">
                          {decisions[ticker]?.action} {decisions[ticker]?.quantity} shares
                        </span>
                      </div>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="pt-4 px-1">
                    <div className="space-y-4">
                      {/* Agent Signals */}
                      <div className="grid grid-cols-1 gap-4">
                        {agents.map(agent => {
                          const signal = analystSignals[agent]?.[ticker];
                          if (!signal) return null;

                          return (
                            <Card key={agent} className="overflow-hidden">
                              <CardHeader className="bg-muted/50 pb-3">
                                <div className="flex items-center justify-between">
                                  <CardTitle className="text-base">
                                    {agentDisplayNames.get(agent) || agent}
                                  </CardTitle>
                                  <div className="flex items-center gap-2">
                                    {getSignalBadge(signal.signal)}
                                    {getConfidenceBadge(signal.confidence)}
                                  </div>
                                </div>
                              </CardHeader>
                              <CardContent className="pt-3">
                                {typeof signal.reasoning === 'string' ? (
                                  <p className="text-sm whitespace-pre-line">
                                    {signal.reasoning}
                                  </p>
                                ) : (
                                  <div className="max-h-48 overflow-y-auto bg-muted/30">
                                    <SyntaxHighlighter
                                      language="json"
                                      style={vscDarkPlus}
                                      className="text-sm rounded-md"
                                      customStyle={{
                                        fontSize: '0.875rem',
                                        margin: 0,
                                        padding: '12px',
                                        backgroundColor: 'hsl(var(--muted))',
                                      }}
                                    >
                                      {JSON.stringify(signal.reasoning, null, 2)}
                                    </SyntaxHighlighter>
                                  </div>
                                )}
                              </CardContent>
                            </Card>
                          );
                        })}
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
