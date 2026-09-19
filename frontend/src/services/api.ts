import { StatusResponse, CalibrationData, UserAuth } from '../types/robosurge';

const API_BASE = ''; // proxied via Vite

export class ApiService {
  private static tokenKey = 'robosurge_jwt';

  public static getToken(): string | null {
    return localStorage.getItem(this.tokenKey);
  }

  public static setToken(token: string): void {
    localStorage.setItem(this.tokenKey, token);
  }

  public static clearToken(): void {
    localStorage.removeItem(this.tokenKey);
  }

  private static getHeaders(): HeadersInit {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    const token = this.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
  }

  public static async autoLogin(): Promise<UserAuth | null> {
    try {
      // Try to login with default admin credentials
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'admin', password: 'admin123' }),
      });
      if (res.ok) {
        const data = await res.json();
        this.setToken(data.token);
        return data;
      }
    } catch {
      // ignore
    }
    return null;
  }

  public static async login(username: string, password: string): Promise<UserAuth> {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Login failed' }));
      throw new Error(err.error || 'Invalid credentials');
    }
    const data = await res.json();
    this.setToken(data.token);
    return data;
  }

  public static async register(username: string, password: string, role: string = 'surgeon'): Promise<UserAuth> {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, role }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Registration failed' }));
      throw new Error(err.error || 'Registration failed');
    }
    const data = await res.json();
    if (data.token) {
      this.setToken(data.token);
    }
    return data;
  }

  public static async getStatus(): Promise<StatusResponse> {
    const res = await fetch(`${API_BASE}/api/status`, {
      headers: this.getHeaders(),
    });
    if (res.status === 401) {
      // Auto-relogin on token expiry
      await this.autoLogin();
      const retry = await fetch(`${API_BASE}/api/status`, { headers: this.getHeaders() });
      if (!retry.ok) throw new Error('Unauthorized');
      return await retry.json();
    }
    if (!res.ok) {
      throw new Error(`Failed to fetch status: ${res.statusText}`);
    }
    return await res.json();
  }

  public static async sendCommand(command: string): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/api/command`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ command }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Command error' }));
      throw new Error(err.detail || 'Failed to process command');
    }
    return await res.json();
  }

  public static async updateBrief(brief: string): Promise<{ status: string; is_doctor_edited?: boolean }> {
    const res = await fetch(`${API_BASE}/api/plan/update-brief`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ brief }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Brief update error' }));
      throw new Error(err.detail || 'Failed to update brief');
    }
    return await res.json();
  }

  public static async executePlan(): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/api/execute`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Execution error' }));
      throw new Error(err.detail || 'Failed to execute plan');
    }
    return await res.json();
  }

  public static async abort(hardExit: boolean = false): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/api/abort`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ hard_exit: hardExit }),
    });
    if (!res.ok) {
      throw new Error('Failed to send abort command');
    }
    return await res.json();
  }

  public static async getCalibration(): Promise<CalibrationData> {
    const res = await fetch(`${API_BASE}/api/calibration`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch calibration');
    return await res.json();
  }

  public static async nudge(dx: number, dy: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/calibration/nudge`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ dx, dy }),
    });
    if (!res.ok) throw new Error('Failed to nudge calibration');
    return await res.json();
  }

  public static async scale(sx: number, sy: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/calibration/scale`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ sx, sy }),
    });
    if (!res.ok) throw new Error('Failed to scale calibration');
    return await res.json();
  }

  public static async resetCalibration(): Promise<any> {
    const res = await fetch(`${API_BASE}/api/calibration/reset`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error('Failed to reset calibration');
    return await res.json();
  }

  public static async setToolOffset(offset: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/calibration/tool_offset`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ offset }),
    });
    if (!res.ok) throw new Error('Failed to set tool offset');
    return await res.json();
  }

  public static async calculateFK(base: number, shoulder: number, elbow: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/calibration/calculate_fk`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ base, shoulder, elbow }),
    });
    if (!res.ok) throw new Error('Failed to calculate FK tool offset');
    return await res.json();
  }
}
