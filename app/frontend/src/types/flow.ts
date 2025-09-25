import type { Edge, Node, Viewport } from '@xyflow/react';

import type { JsonObject } from './json';

export type FlowNodeData = JsonObject & {
  internal_state?: Record<string, unknown>;
};

export interface Flow {
  id: number;
  name: string;
  description?: string;
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  viewport?: Viewport;
  data?: JsonObject;
  is_template: boolean;
  tags?: string[];
  created_at: string;
  updated_at?: string;
}
