import { Pod, PodLifecycleEvent, LifecycleConfig } from '@/types/pod';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function handleError(response: Response, fallback: string): Promise<never> {
  let detail = fallback;
  try {
    const body = await response.json();
    detail = body.detail || detail;
  } catch {
    // Non-JSON error response (e.g. proxy error page)
  }
  throw new Error(detail);
}

export const podsApi = {
  getPods: async (): Promise<Pod[]> => {
    const response = await fetch(`${API_BASE_URL}/pods`);
    if (!response.ok) await handleError(response, 'Failed to fetch pods');
    return response.json();
  },

  getPodHistory: async (podId: string): Promise<PodLifecycleEvent[]> => {
    const response = await fetch(`${API_BASE_URL}/pods/${encodeURIComponent(podId)}/history`);
    if (!response.ok) await handleError(response, 'Failed to fetch pod history');
    return response.json();
  },

  getLifecycleConfig: async (): Promise<LifecycleConfig> => {
    const response = await fetch(`${API_BASE_URL}/pods/config`);
    if (!response.ok) await handleError(response, 'Failed to fetch lifecycle config');
    return response.json();
  },

  promotePod: async (podId: string): Promise<{ message: string }> => {
    const response = await fetch(`${API_BASE_URL}/pods/${encodeURIComponent(podId)}/promote`, {
      method: 'POST',
    });
    if (!response.ok) await handleError(response, 'Failed to promote pod');
    return response.json();
  },

  demotePod: async (podId: string): Promise<{ message: string }> => {
    const response = await fetch(`${API_BASE_URL}/pods/${encodeURIComponent(podId)}/demote`, {
      method: 'POST',
    });
    if (!response.ok) await handleError(response, 'Failed to demote pod');
    return response.json();
  },
};
