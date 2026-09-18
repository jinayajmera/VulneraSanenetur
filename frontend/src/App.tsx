import React, { useState, useEffect, useRef } from 'react';
import { Settings, Bell, Send, Mic, Play, Square, LogOut, User as UserIcon, Home, ArrowLeft } from 'lucide-react';
import { LandingPage } from './components/LandingPage';
import './index.css';

interface SystemStatus {
  online: boolean;
  time: string;
  vitals: {
    camera: string;
    serial: string;
    groq: string;
  };
  scene: {
    arms: Array<{id: number, x: number, y: number, z: number, source: string}>;
    landmarks: Array<{name: string, x: number, y: number, z: number, conf: number}>;
    tool_offset: number;
  };
  planning: {
    command: string;
    plan: any;
    validation: any;
    nl_translation?: string;
  };
  logs: Array<{time: string, tag: string, message: string}>;
}

const API_BASE = "http://localhost:8080/api";
const AUTH_BASE = "http://localhost:8080/auth";

function App() {
  const [viewMode, setViewMode] = useState<'landing' | 'console'>('landing');
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [role, setRole] = useState<string | null>(localStorage.getItem('role'));
  const [isLogin, setIsLogin] = useState(true);
  const [authForm, setAuthForm] = useState({ username: '', password: '', role: 'doctor' });

  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [command, setCommand] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const endpoint = isLogin ? '/login' : '/signup';
    try {
      const res = await fetch(AUTH_BASE + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authForm)
      });
      const data = await res.json();
      if (res.ok && isLogin) {
        localStorage.setItem('token', data.token);
        localStorage.setItem('role', data.role);
        setToken(data.token);
        setRole(data.role);
        setViewMode('console');
      } else if (res.ok) {
        alert("Signup successful. Please login.");
        setIsLogin(true);
      } else {
        alert("Auth Error: " + data.error);
      }
    } catch (err) {
      alert("Auth failed.");
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    setToken(null);
    setRole(null);
  };

  // Poll status when in console mode & logged in
  useEffect(() => {
    if (!token) return;
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/status`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.status === 401 || res.status === 403) {
          logout();
          return;
        }
        const data = await res.json();
        setStatus(data);
      } catch (err) {
        // Silent fail for polling
      }
    };
    
    fetchStatus();
    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, [token]);

  // Auto-scroll logs
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [status?.logs]);

  const handleCommandSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!command.trim() || isProcessing || !token) return;
    
    setIsProcessing(true);
    try {
      await fetch(`${API_BASE}/command`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}` 
        },
        body: JSON.stringify({ command })
      });
      setCommand("");
    } catch (err) {
      console.error(err);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleExecute = async () => {
    try {
      await fetch(`${API_BASE}/execute`, { 
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` } 
      });
    } catch (err) {}
  };

  const handleAbort = async () => {
    try {
      await fetch(`${API_BASE}/abort`, { 
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
    } catch (err) {}
  };

  // 1. RENDER LANDING PAGE
  if (viewMode === 'landing') {
    return (
      <LandingPage
        token={token}
        role={role}
        onLaunchConsole={() => setViewMode('console')}
        onOpenAuth={() => setViewMode('console')}
      />
    );
  }

  // 2. RENDER AUTH MODAL IF NOT LOGGED IN
  if (!token) {
    return (
      <div style={{
        position: 'relative',
        display: 'flex',
        minHeight: '100vh',
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: '#07090e',
        color: '#f8fafc',
        fontFamily: "'Plus Jakarta Sans', sans-serif"
      }}>
        {/* Radial Background */}
        <div className="radial-mesh" />

        <div className="glass-panel" style={{ width: '420px', padding: '2.5rem', borderRadius: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
            <button 
              onClick={() => setViewMode('landing')}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--accent-cyan)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '0.85rem',
                fontFamily: "'JetBrains Mono', monospace"
              }}
            >
              <ArrowLeft size={16} /> Back to Landing Page
            </button>
            <div className="pulse-dot" />
          </div>

          <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
            <h2 style={{ fontSize: '1.75rem', fontWeight: 800, letterSpacing: '0.5px' }}>ROBOSURGE AUTH</h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Secure Doctor / Administrator Access Portal
            </p>
          </div>

          <form onSubmit={handleAuthSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
            <div>
              <label style={{ fontSize: '0.78rem', fontFamily: "'JetBrains Mono', monospace", color: 'var(--text-muted)' }}>USERNAME</label>
              <input 
                style={{
                  width: '100%',
                  marginTop: '4px',
                  padding: '12px 16px',
                  borderRadius: '10px',
                  background: 'rgba(15, 23, 42, 0.9)',
                  border: '1px solid var(--border-glow)',
                  color: '#fff',
                  fontFamily: "'JetBrains Mono', monospace",
                  outline: 'none'
                }} 
                placeholder="Enter username (e.g. admin)" 
                value={authForm.username} 
                onChange={e => setAuthForm({...authForm, username: e.target.value})} 
                required 
              />
            </div>

            <div>
              <label style={{ fontSize: '0.78rem', fontFamily: "'JetBrains Mono', monospace", color: 'var(--text-muted)' }}>PASSWORD</label>
              <input 
                style={{
                  width: '100%',
                  marginTop: '4px',
                  padding: '12px 16px',
                  borderRadius: '10px',
                  background: 'rgba(15, 23, 42, 0.9)',
                  border: '1px solid var(--border-glow)',
                  color: '#fff',
                  fontFamily: "'JetBrains Mono', monospace",
                  outline: 'none'
                }} 
                type="password" 
                placeholder="Enter password (e.g. admin123)" 
                value={authForm.password} 
                onChange={e => setAuthForm({...authForm, password: e.target.value})} 
                required 
              />
            </div>

            {!isLogin && (
              <div>
                <label style={{ fontSize: '0.78rem', fontFamily: "'JetBrains Mono', monospace", color: 'var(--text-muted)' }}>ASSIGNED ROLE</label>
                <select 
                  style={{
                    width: '100%',
                    marginTop: '4px',
                    padding: '12px 16px',
                    borderRadius: '10px',
                    background: 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid var(--border-glow)',
                    color: '#fff',
                    fontFamily: "'JetBrains Mono', monospace",
                    outline: 'none'
                  }} 
                  value={authForm.role} 
                  onChange={e => setAuthForm({...authForm, role: e.target.value})}
                >
                  <option value="doctor">Doctor (Execution Enabled)</option>
                  <option value="admin">Administrator</option>
                </select>
              </div>
            )}

            <button type="submit" className="btn-primary" style={{ width: '100%', marginTop: '0.5rem' }}>
              {isLogin ? 'LOGIN TO CONSOLE' : 'REGISTER ACCOUNT'}
            </button>
          </form>

          <div 
            style={{ textAlign: 'center', marginTop: '1.5rem', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary)' }} 
            onClick={() => setIsLogin(!isLogin)}
          >
            {isLogin ? "Need an account? Sign up (Admin Required)" : "Already registered? Return to Login"}
          </div>
        </div>
      </div>
    );
  }

  // 3. RENDER FULL CONTROL INTERFACE DASHBOARD
  const plan = status?.planning?.plan;
  const validation = status?.planning?.validation;
  const nl_translation = status?.planning?.nl_translation;

  return (
    <div className="app-container">
      {/* HEADER */}
      <header className="top-bar">
        <div className="flex-row gap-2">
          <button 
            onClick={() => setViewMode('landing')}
            className="btn btn-small flex-row gap-2"
            title="Return to Landing Page"
            style={{ marginRight: '8px' }}
          >
            <Home size={14} />
            <span>LANDING PAGE</span>
          </button>
          <div className="status-dot status-nominal" style={{ width: '14px', height: '14px', borderRadius: '4px' }}></div>
          <h2 style={{ letterSpacing: '1.5px', fontSize: '1.1rem', margin: 0 }}>ROBOSURGE <span style={{ opacity: 0.6, fontWeight: 'normal', fontSize: '0.9rem' }}>CONTROL INTERFACE</span></h2>
        </div>
        
        <div className="flex-row gap-4">
          <div className="flex-row gap-2 text-sm mono font-bold">
            <UserIcon size={16} />
            <span style={{ textTransform: 'uppercase' }}>ROLE: {role}</span>
          </div>
          <div className="flex-row gap-2 text-sm mono font-bold">
            <span className={`status-dot ${status?.online ? 'status-nominal' : 'status-alert'}`}></span>
            {status?.online ? 'SYSTEM ONLINE' : 'SYSTEM OFFLINE'}
          </div>
          <div className="text-sm mono" style={{ opacity: 0.7 }}>
            {status?.time || 'UTC --:--:--'}
          </div>
          <button className="btn btn-small" title="Settings"><Settings size={16} /></button>
          <button className="btn btn-small" title="Logout" onClick={logout}><LogOut size={16} /></button>
        </div>
      </header>

      <div className="main-content">
        
        {/* LEFT COLUMN */}
        <div className="col-left">
          
          {/* CAMERA VIEW */}
          <div className="panel" style={{ flex: 1.5 }}>
            <div className="panel-header">
              <div className="flex-row gap-2">
                <Play size={16} />
                <span>PRIMARY CAMERA - TRACKING VIEW</span>
              </div>
              <div className="flex-row gap-2 text-xs">
                <span className={`status-dot ${status?.vitals?.camera === 'LIVE' ? 'status-nominal' : 'status-alert'}`}></span>
                {status?.vitals?.camera || 'OFFLINE'}
              </div>
            </div>
            <div className="panel-content" style={{ padding: 0, backgroundColor: '#000', display: 'flex', justifyContent: 'center', alignItems: 'center', overflow: 'hidden' }}>
              <img 
                src="http://localhost:8000/api/camera/feed" 
                alt="Camera Feed" 
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                  (e.target as HTMLImageElement).nextElementSibling?.removeAttribute('style');
                }}
              />
              <div style={{ display: 'none', color: '#888', fontFamily: 'Space Mono' }}>
                CAMERA FEED UNAVAILABLE
              </div>
            </div>
          </div>

          {/* COMMAND CONSOLE */}
          <div className="panel" style={{ flex: 1, minHeight: '250px' }}>
            <div className="panel-header">
              <span>&gt;_ COMMAND CONSOLE</span>
              <div className="flex-row gap-2 text-xs">
                <span>{status?.logs?.length || 0} msgs</span>
              </div>
            </div>
            <div className="panel-content mono" style={{ padding: '0.5rem', display: 'flex', flexDirection: 'column' }}>
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {status?.logs?.map((log, i) => (
                  <div key={i} className="log-line">
                    <span className="log-time">{log.time}</span>
                    <span className={`log-tag tag-${log.tag}`}>{log.tag}</span>
                    <span style={{ opacity: log.tag === 'SYS' ? 0.8 : 1 }}>{log.message}</span>
                  </div>
                ))}
                <div ref={logsEndRef} />
              </div>
            </div>
            <form onSubmit={handleCommandSubmit} className="input-bar">
              <span className="font-bold">&gt;</span>
              <input 
                type="text" 
                className="input-field"
                placeholder={isProcessing ? "Processing command..." : "Type command... (e.g. make a 3mm incision at landmark A)"}
                value={command}
                onChange={e => setCommand(e.target.value)}
                disabled={isProcessing}
              />
              <button type="submit" className="btn flex-row gap-2" disabled={isProcessing}>
                <span>SEND</span>
              </button>
            </form>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="col-right">
          
          {/* SYSTEM VITALS */}
          <div className="panel" style={{ flex: 'none' }}>
            <div className="panel-header">
              <span>⚡ SYSTEM VITALS</span>
              <div className="flex-row gap-2 text-xs">
                <span className="status-dot status-nominal"></span>
                ALL NOMINAL
              </div>
            </div>
            <div className="panel-content flex-col gap-2 text-sm mono">
              
              <div className="flex-row" style={{ justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid rgba(0,0,0,0.1)' }}>
                <span>ESP32 Serial</span>
                <span className={`font-bold ${status?.vitals?.serial === 'CONNECTED' ? 'status-nominal' : 'status-warn'}`}>
                  {status?.vitals?.serial || 'UNKNOWN'}
                </span>
              </div>
              
              <div className="flex-row" style={{ justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid rgba(0,0,0,0.1)' }}>
                <span>Groq API</span>
                <span className="font-bold">{status?.vitals?.groq || 'UNKNOWN'}</span>
              </div>
              
              <div className="flex-col gap-2" style={{ marginTop: '0.5rem' }}>
                <div className="font-bold uppercase text-xs" style={{ opacity: 0.6 }}>Robotic Arms</div>
                {status?.scene?.arms?.map(arm => (
                  <div key={arm.id} className="flex-row" style={{ justifyContent: 'space-between' }}>
                    <span>Arm {arm.id} ({arm.source})</span>
                    <span>X:{arm.x > 0 ? '+':''}{arm.x.toFixed(1)} Y:{arm.y > 0 ? '+':''}{arm.y.toFixed(1)} Z:{arm.z.toFixed(1)}</span>
                  </div>
                ))}
              </div>

              <div className="flex-col gap-2" style={{ marginTop: '0.5rem' }}>
                <div className="font-bold uppercase text-xs" style={{ opacity: 0.6 }}>Landmarks</div>
                {status?.scene?.landmarks?.length ? status.scene.landmarks.map((lm, i) => (
                  <div key={i} className="flex-row" style={{ justifyContent: 'space-between' }}>
                    <span>{lm.name}</span>
                    <span style={{ opacity: 0.7 }}>C: {lm.conf.toFixed(2)}</span>
                  </div>
                )) : <span style={{ opacity: 0.5 }}>None detected</span>}
              </div>

            </div>
          </div>

          {/* PROCEDURE PREVIEW */}
          <div className="panel" style={{ flex: 1, backgroundColor: plan ? '#fff' : 'var(--color-panel)' }}>
            <div className="panel-header" style={{ backgroundColor: plan ? '#feca57' : 'var(--color-header)' }}>
              <span>📋 PROCEDURE PLAN</span>
              {validation && (
                <span className={`text-xs font-bold ${validation.ok ? '' : 'tag-ALERT'}`} style={{ padding: '2px 6px', borderRadius: '2px', backgroundColor: validation.ok ? 'var(--color-nominal)' : 'var(--color-alert)', color: '#fff' }}>
                  {validation.ok ? 'VALIDATED' : 'REJECTED'}
                </span>
              )}
            </div>
            
            <div className="panel-content text-sm mono">
              {!plan ? (
                <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', opacity: 0.4, textAlign: 'center' }}>
                  AWAITING COMMAND...
                </div>
              ) : (
                <div className="flex-col gap-2">
                  <div className="font-bold uppercase" style={{ fontSize: '1rem', borderBottom: '2px solid #000', paddingBottom: '0.5rem' }}>
                    {plan.procedure}
                  </div>
                  
                  {/* DISPLAY NL TRANSLATION */}
                  <div style={{ backgroundColor: '#f0f9ff', border: '1px solid #54a0ff', padding: '0.75rem', borderRadius: '4px', marginBottom: '0.5rem' }}>
                    <div className="font-bold text-xs" style={{ color: '#54a0ff', marginBottom: '4px' }}>NL DOCTOR SUMMARY</div>
                    {nl_translation ? (
                       <span style={{ fontFamily: 'Inter, sans-serif' }}>{nl_translation}</span>
                    ) : (
                       <span style={{ fontStyle: 'italic', opacity: 0.5 }}>Translating plan to natural language...</span>
                    )}
                  </div>
                  
                  {validation && !validation.ok && (
                    <div style={{ backgroundColor: 'var(--color-alert)', color: '#fff', padding: '0.5rem', borderRadius: '4px', border: '1px solid #000', marginBottom: '0.5rem' }}>
                      <div className="font-bold">VALIDATION ERRORS:</div>
                      <ul style={{ paddingLeft: '1rem', margin: 0 }}>
                        {validation.errors.map((e: string, i: number) => <li key={i}>{e}</li>)}
                      </ul>
                    </div>
                  )}
                  
                  {plan.safety_notes && (
                    <div style={{ backgroundColor: 'var(--color-warn)', color: '#000', padding: '0.5rem', borderRadius: '4px', border: '1px solid #000' }}>
                      <strong>NOTE:</strong> {plan.safety_notes}
                    </div>
                  )}
                  
                  <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
                    <div className="flex-col flex-1">
                      <div className="font-bold text-xs uppercase" style={{ opacity: 0.6 }}>ARM 1 ({plan.arm1.role})</div>
                      <div className="text-xs">{plan.arm1.waypoints.length} waypoints</div>
                    </div>
                    <div className="flex-col flex-1">
                      <div className="font-bold text-xs uppercase" style={{ opacity: 0.6 }}>ARM 2 ({plan.arm2.role})</div>
                      <div className="text-xs">{plan.arm2.waypoints.length} waypoints</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
            
            {/* EXECUTION CONTROLS */}
            {plan && (
              <div className="input-bar" style={{ justifyContent: 'space-between', backgroundColor: '#eee' }}>
                <button 
                  className="btn flex-row gap-2" 
                  style={{ backgroundColor: 'var(--color-alert)', color: '#fff' }}
                  onClick={handleAbort}
                >
                  <Square size={16} fill="currentColor" />
                  <span>ABORT</span>
                </button>
                <button 
                  className="btn flex-row gap-2" 
                  style={{ backgroundColor: validation?.ok ? 'var(--color-nominal)' : '#ccc', color: '#fff', pointerEvents: validation?.ok ? 'auto' : 'none', opacity: validation?.ok ? 1 : 0.5 }}
                  onClick={handleExecute}
                  disabled={!validation?.ok || role !== 'doctor'}
                >
                  <Play size={16} fill="currentColor" />
                  <span>{role === 'doctor' ? 'EXECUTE PLAN' : 'EXECUTE (DOCTOR ONLY)'}</span>
                </button>
              </div>
            )}
            {!plan && (
              <div className="input-bar" style={{ justifyContent: 'center' }}>
                <button 
                  className="btn flex-row gap-2" 
                  style={{ backgroundColor: 'var(--color-alert)', color: '#fff', width: '100%', justifyContent: 'center' }}
                  onClick={handleAbort}
                >
                  <Square size={16} fill="currentColor" />
                  <span>EMERGENCY ABORT</span>
                </button>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}

export default App;
