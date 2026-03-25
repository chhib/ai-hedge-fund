export interface Pod {
  name: string;
  analyst: string;
  enabled: boolean;
  max_picks: number;
  tier: 'paper' | 'live';
  starting_capital?: number;
  schedule: string;
  effective_tier: 'paper' | 'live';
  days_in_tier: number;
  next_evaluation_date: string;
  latest_event?: PodLifecycleEvent;
  metrics?: PodMetrics;
}

export interface PodLifecycleEvent {
  id: number;
  pod_id: string;
  event_type: string;
  old_tier: string;
  new_tier: string;
  reason: string;
  source: string;
  metrics_json?: Record<string, any>;
  created_at: string;
}

export interface PodMetrics {
  total_value: number;
  cash: number;
  positions_value: number;
  cumulative_return_pct: number;
  starting_capital: number;
  sharpe_ratio?: number;
  max_drawdown?: number;
  current_drawdown_pct?: number;
  observation_days?: number;
  total_trades?: number;
  win_rate?: number;
  [key: string]: any;
}

export interface LifecycleConfig {
  min_history_days: number;
  promotion_sharpe: number;
  promotion_return_pct: number;
  promotion_drawdown_pct: number;
  maintenance_sharpe: number;
  hard_stop_drawdown_pct: number;
  evaluation_schedule: string;
  next_evaluation_date: string;
}
