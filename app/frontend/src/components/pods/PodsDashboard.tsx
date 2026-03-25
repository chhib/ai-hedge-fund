import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { podsApi } from '@/services/pods-api';
import { LifecycleConfig, Pod, PodLifecycleEvent } from '@/types/pod';
import { AlertCircle, RefreshCw, Settings, Info, Shield } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { LifecycleHistory } from './LifecycleHistory';
import { PodCard } from './PodCard';

export function PodsDashboard() {
  const [pods, setPods] = useState<Pod[]>([]);
  const [config, setConfig] = useState<LifecycleConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyPod, setHistoryPod] = useState<string | null>(null);
  const [historyEvents, setHistoryEvents] = useState<PodLifecycleEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [confirmAction, setConfirmAction] = useState<{ podId: string; action: 'promote' | 'demote' } | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [podsData, configData] = await Promise.all([
        podsApi.getPods(),
        podsApi.getLifecycleConfig(),
      ]);
      setPods(podsData);
      setConfig(configData);
    } catch (error) {
      console.error('Failed to fetch pods data:', error);
      toast.error('Failed to load pods dashboard');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handlePromote = (podId: string) => {
    setConfirmAction({ podId, action: 'promote' });
  };

  const handleDemote = (podId: string) => {
    setConfirmAction({ podId, action: 'demote' });
  };

  const executeConfirmedAction = async () => {
    if (!confirmAction) return;
    const { podId, action } = confirmAction;
    setConfirmAction(null);
    try {
      const res = action === 'promote'
        ? await podsApi.promotePod(podId)
        : await podsApi.demotePod(podId);
      toast.success(res.message);
      fetchData();
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to ${action} pod`;
      toast.error(message);
    }
  };

  const handleViewHistory = async (podId: string) => {
    setHistoryPod(podId);
    setHistoryLoading(true);
    try {
      const events = await podsApi.getPodHistory(podId);
      setHistoryEvents(events);
    } catch (error) {
      toast.error('Failed to load pod history');
    } finally {
      setHistoryLoading(false);
    }
  };

  const livePods = pods.filter(p => p.effective_tier === 'live');
  const paperPods = pods.filter(p => p.effective_tier === 'paper');

  if (loading) {
    return (
      <div className="p-8 space-y-8">
        <div className="flex justify-between items-center">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 h-full overflow-auto bg-background/50">
      <div className="flex flex-col gap-6 max-w-7xl mx-auto">
        <div className="flex justify-between items-end">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Trading Pod Shop</h1>
            <p className="text-muted-foreground mt-1">
              Independent analyst pods with automated lifecycle promotion.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={fetchData}>
              <RefreshCw className="w-4 h-4 mr-2" />
              Refresh
            </Button>
            {config && (
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm">
                    <Settings className="w-4 h-4 mr-2" />
                    Policy
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-md">
                  <DialogHeader>
                    <DialogTitle>Lifecycle Policy</DialogTitle>
                    <DialogDescription>
                      Automated rules for pod promotion and maintenance.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4 py-4">
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div className="text-muted-foreground">Min History:</div>
                      <div className="font-medium">{config.min_history_days} days</div>
                      <div className="text-muted-foreground">Promotion Sharpe:</div>
                      <div className="font-medium">{config.promotion_sharpe}</div>
                      <div className="text-muted-foreground">Promotion Return:</div>
                      <div className="font-medium">{config.promotion_return_pct}%</div>
                      <div className="text-muted-foreground">Promotion Drawdown:</div>
                      <div className="font-medium">{"< "}{config.promotion_drawdown_pct}%</div>
                      <div className="text-muted-foreground">Maintenance Sharpe:</div>
                      <div className="font-medium">{config.maintenance_sharpe}</div>
                      <div className="text-muted-foreground">Hard Stop Drawdown:</div>
                      <div className="font-medium text-red-500">{config.hard_stop_drawdown_pct}%</div>
                      <div className="text-muted-foreground">Evaluation Schedule:</div>
                      <div className="font-medium">{config.evaluation_schedule}</div>
                      <div className="text-muted-foreground">Next Evaluation:</div>
                      <div className="font-medium">{new Date(config.next_evaluation_date).toLocaleDateString()}</div>
                    </div>
                    <p className="text-xs text-muted-foreground italic">
                      Manual overrides are re-evaluated on the next scheduled cycle.
                    </p>
                  </div>
                </DialogContent>
              </Dialog>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-2">
          <Card className="bg-green-500/5 border-green-500/10">
            <CardHeader className="py-3 px-4 flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-xs font-medium text-green-600 uppercase tracking-wider">Live Pods</CardTitle>
              <Shield className="h-3 w-3 text-green-500" />
            </CardHeader>
            <CardContent className="py-2 px-4">
              <div className="text-2xl font-bold">{livePods.length}</div>
            </CardContent>
          </Card>
          <Card className="bg-blue-500/5 border-blue-500/10">
            <CardHeader className="py-3 px-4 flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-xs font-medium text-blue-600 uppercase tracking-wider">Paper Pods</CardTitle>
              <RefreshCw className="h-3 w-3 text-blue-500" />
            </CardHeader>
            <CardContent className="py-2 px-4">
              <div className="text-2xl font-bold">{paperPods.length}</div>
            </CardContent>
          </Card>
          <Card className="bg-muted/30 border-muted">
            <CardHeader className="py-3 px-4 flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Total Tickers</CardTitle>
              <Info className="h-3 w-3 text-muted-foreground" />
            </CardHeader>
            <CardContent className="py-2 px-4">
              <div className="text-2xl font-bold">
                {pods.reduce((sum, p) => sum + (p.enabled ? p.max_picks : 0), 0)}
              </div>
            </CardContent>
          </Card>
          <Card className="bg-muted/30 border-muted">
            <CardHeader className="py-3 px-4 flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Evaluation Cycle</CardTitle>
              <AlertCircle className="h-3 w-3 text-muted-foreground" />
            </CardHeader>
            <CardContent className="py-2 px-4">
              <div className="text-sm font-bold truncate">{config?.evaluation_schedule ?? 'Unknown'}</div>
            </CardContent>
          </Card>
        </div>

        <Tabs defaultValue="all" className="w-full">
          <TabsList className="mb-4">
            <TabsTrigger value="all">All Pods ({pods.length})</TabsTrigger>
            <TabsTrigger value="live">Live Tiers ({livePods.length})</TabsTrigger>
            <TabsTrigger value="paper">Paper Tiers ({paperPods.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="all" className="m-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {pods.map(pod => (
                <PodCard
                  key={pod.name}
                  pod={pod}
                  onPromote={handlePromote}
                  onDemote={handleDemote}
                  onViewHistory={handleViewHistory}
                />
              ))}
            </div>
          </TabsContent>

          <TabsContent value="live" className="m-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {livePods.map(pod => (
                <PodCard
                  key={pod.name}
                  pod={pod}
                  onPromote={handlePromote}
                  onDemote={handleDemote}
                  onViewHistory={handleViewHistory}
                />
              ))}
              {livePods.length === 0 && (
                <div className="col-span-full py-20 text-center border-2 border-dashed rounded-lg bg-muted/20">
                  <Shield className="w-12 h-12 mx-auto text-muted-foreground/30 mb-4" />
                  <h3 className="text-lg font-medium text-muted-foreground">No Live Pods</h3>
                  <p className="text-sm text-muted-foreground">Promote paper pods to deploy live capital.</p>
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="paper" className="m-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {paperPods.map(pod => (
                <PodCard
                  key={pod.name}
                  pod={pod}
                  onPromote={handlePromote}
                  onDemote={handleDemote}
                  onViewHistory={handleViewHistory}
                />
              ))}
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {/* Lifecycle History Dialog */}
      <Dialog open={!!historyPod} onOpenChange={(open) => !open && setHistoryPod(null)}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Lifecycle History: {historyPod}</DialogTitle>
            <DialogDescription>
              Audit trail of tier transitions and automated evaluations.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            {historyLoading ? (
              <div className="space-y-4">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <LifecycleHistory events={historyEvents} />
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Promote/Demote Confirmation Dialog */}
      <Dialog open={!!confirmAction} onOpenChange={(open) => !open && setConfirmAction(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {confirmAction?.action === 'promote' ? 'Promote Pod to Live' : 'Demote Pod to Paper'}
            </DialogTitle>
            <DialogDescription>
              {confirmAction?.action === 'promote'
                ? `Promoting "${confirmAction.podId}" will move it to live trading with real capital. This override will be re-evaluated on the next scheduled evaluation cycle.`
                : `Demoting "${confirmAction?.podId}" will move it back to paper trading. This override will be re-evaluated on the next scheduled evaluation cycle.`
              }
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" size="sm" onClick={() => setConfirmAction(null)}>
              Cancel
            </Button>
            <Button
              variant={confirmAction?.action === 'promote' ? 'default' : 'destructive'}
              size="sm"
              onClick={executeConfirmedAction}
            >
              {confirmAction?.action === 'promote' ? 'Confirm Promote' : 'Confirm Demote'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
