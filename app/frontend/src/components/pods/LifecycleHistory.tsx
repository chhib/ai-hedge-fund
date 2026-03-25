import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PodLifecycleEvent } from '@/types/pod';
import { cn } from '@/lib/utils';

interface LifecycleHistoryProps {
  events: PodLifecycleEvent[];
}

export function LifecycleHistory({ events }: LifecycleHistoryProps) {
  if (events.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground italic">
        No lifecycle events recorded for this pod yet.
      </div>
    );
  }

  const formatEventDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const getEventBadge = (type: string) => {
    switch (type) {
      case 'promotion':
      case 'manual_promotion':
        return <Badge className="bg-green-600">Promotion</Badge>;
      case 'demotion':
      case 'manual_demotion':
      case 'drawdown_stop':
        return <Badge variant="destructive">Demotion</Badge>;
      case 'weekly_maintenance':
        return <Badge variant="outline">Maintenance</Badge>;
      default:
        return <Badge variant="secondary">{type}</Badge>;
    }
  };

  return (
    <div className="max-h-[60vh] overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Event</TableHead>
            <TableHead>From → To</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Reason</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...events].reverse().map((event) => (
            <TableRow key={event.id}>
              <TableCell className="text-xs whitespace-nowrap">
                {formatEventDate(event.created_at)}
              </TableCell>
              <TableCell>
                {getEventBadge(event.event_type)}
              </TableCell>
              <TableCell className="text-xs font-mono">
                {event.old_tier} → {event.new_tier}
              </TableCell>
              <TableCell className="text-xs">
                {event.source}
              </TableCell>
              <TableCell className="text-xs max-w-md">
                {event.reason}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
