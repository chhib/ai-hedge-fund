import { Pod, PodLifecycleEvent, LifecycleConfig } from '@/types/pod';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const podsApi = {
  getPods: async (): Promise<Pod[]> => {
    const response = await fetch(`${API_BASE_URL}/pods`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to fetch pods');
    }
    return response.json();
  },

  getPodHistory: async (podId: string): Promise<PodLifecycleEvent[]> => {
    const response = await fetch(`${API_BASE_URL}/pods/${podId}/history`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to fetch pod history');
    }
    return response.json();
  },

  getLifecycleConfig: async (): Promise<LifecycleConfig> => {
    const response = await fetch(`${API_BASE_URL}/pods/config`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to fetch lifecycle config');
    }
    return response.json();
  },

  promotePod: async (podId: string): Promise<{ message: string }> => {
    const response = await fetch(`${API_BASE_URL}/pods/${podId}/promote`, {
      method: 'POST',
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to promote pod');
    }
    return response.json();
  },

  demotePod: async (podId: string): Promise<{ message: string }> => {
    const response = await fetch(`${API_BASE_URL}/pods/${podId}/demote`, {
      method: 'POST',
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to demote pod');
    }
    return response.json();
  },
};
