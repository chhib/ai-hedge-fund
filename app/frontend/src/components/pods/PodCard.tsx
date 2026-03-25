import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { Pod } from '@/types/pod';
import { Calendar, Clock, History, StopCircle, TrendingUp } from 'lucide-react';

interface PodCardProps {
  pod: Pod;
  onPromote: (podId: string) => void;
  onDemote: (podId: string) => void;
  onViewHistory: (podId: string) => void;
}

export function PodCard({ pod, onPromote, onDemote, onViewHistory }: PodCardProps) {
  const isLive = pod.effective_tier === 'live';
  const metrics = pod.metrics;

  const formatCurrency = (val?: number) => {
    if (val === undefined) return 'N/A';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
  };

  const formatPercent = (val?: number) => {
    if (val === undefined) return 'N/A';
    return `${val.toFixed(2)}%`;
  };

  return (
    <Card className={cn("overflow-hidden transition-all duration-200 border-2", 
      isLive ? "border-green-500/20 shadow-green-500/5" : "border-blue-500/20 shadow-blue-500/5")}>
      <CardHeader className="pb-2">
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="text-xl font-bold">{pod.name}</CardTitle>
            <CardDescription className="flex items-center mt-1">
              <Badge variant="outline" className="mr-2">{pod.analyst}</Badge>
              <span className="text-xs text-muted-foreground flex items-center">
                <Clock className="w-3 h-3 mr-1" />
                {pod.schedule}
              </span>
            </CardDescription>
          </div>
          <Badge variant="secondary" className={cn(
            isLive ? "bg-green-600 hover:bg-green-700" : "bg-blue-600 hover:bg-blue-700",
            "text-white font-bold"
          )}>
            {pod.effective_tier.toUpperCase()}
          </Badge>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Total Value</p>
            <p className="text-lg font-semibold tabular-nums">
              {formatCurrency(metrics?.total_value)}
            </p>
          </div>
          <div className="space-y-1 text-right">
            <p className="text-xs text-muted-foreground">Return</p>
            <p className={cn(
              "text-lg font-bold tabular-nums flex items-center justify-end",
              (metrics?.cumulative_return_pct ?? 0) >= 0 ? "text-green-500" : "text-red-500"
            )}>
              {(metrics?.cumulative_return_pct ?? 0) >= 0 ? <TrendingUp className="w-4 h-4 mr-1" /> : <TrendingUp className="w-4 h-4 mr-1 rotate-180" />}
              {formatPercent(metrics?.cumulative_return_pct)}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 text-xs py-2 border-y border-border/50">
          <div className="text-center">
            <p className="text-muted-foreground mb-1">Sharpe</p>
            <p className="font-medium">{metrics?.sharpe_ratio?.toFixed(2) ?? 'N/A'}</p>
          </div>
          <div className="text-center border-x border-border/50">
            <p className="text-muted-foreground mb-1">Max DD</p>
            <p className="font-medium text-red-400">{formatPercent(metrics?.max_drawdown)}</p>
          </div>
          <div className="text-center">
            <p className="text-muted-foreground mb-1">Days</p>
            <p className="font-medium">{metrics?.observation_days ?? 0}</p>
          </div>
        </div>

        <div className="flex flex-col gap-2 pt-1">
          <div className="flex justify-between items-center text-xs">
            <span className="text-muted-foreground flex items-center">
              <Calendar className="w-3 h-3 mr-1" />
              In Tier
            </span>
            <span className="font-medium">{pod.days_in_tier} days</span>
          </div>
          <div className="flex justify-between items-center text-xs">
            <span className="text-muted-foreground flex items-center">
              <Clock className="w-3 h-3 mr-1" />
              Next Eval
            </span>
            <span className="font-medium">{new Date(pod.next_evaluation_date).toLocaleDateString()}</span>
          </div>
        </div>

        {pod.latest_event && (
          <div className="text-[10px] p-2 bg-muted/50 rounded italic text-muted-foreground border border-border/30">
            Latest: {pod.latest_event.event_type} - {pod.latest_event.reason}
          </div>
        )}
      </CardContent>

      <CardFooter className="flex gap-2 pt-2 border-t border-border/50">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button 
                variant="outline" 
                size="sm" 
                className="flex-1 text-xs"
                onClick={() => onViewHistory(pod.name)}
              >
                <History className="w-3 h-3 mr-1" />
                History
              </Button>
            </TooltipTrigger>
            <TooltipContent>View lifecycle event history</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {isLive ? (
          <Button 
            variant="destructive" 
            size="sm" 
            className="flex-1 text-xs"
            onClick={() => onDemote(pod.name)}
          >
            <StopCircle className="w-3 h-3 mr-1" />
            Demote
          </Button>
        ) : (
          <Button 
            variant="default" 
            size="sm" 
            className="flex-1 text-xs bg-green-600 hover:bg-green-700 text-white"
            onClick={() => onPromote(pod.name)}
          >
            <TrendingUp className="w-3 h-3 mr-1" />
            Promote
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
