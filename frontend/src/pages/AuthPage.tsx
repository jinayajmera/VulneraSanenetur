import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { 
  Bot, 
  Shield, 
  User, 
  Lock, 
  ArrowLeft, 
  CheckCircle2, 
  AlertCircle, 
  UserPlus, 
  LogIn, 
  Sparkles,
  Stethoscope,
  Terminal
} from 'lucide-react';
import { ApiService } from '../services/api';
import { UserAuth } from '../types/robosurge';

interface AuthPageProps {
  currentUser: UserAuth | null;
  onLoginSuccess: (user: UserAuth) => void;
  onLogout: () => void;
}

export const AuthPage: React.FC<AuthPageProps> = ({
  currentUser,
  onLoginSuccess,
  onLogout,
}) => {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');

  // Login form state
  const [loginUser, setLoginUser] = useState('admin');
  const [loginPass, setLoginPass] = useState('admin123');

  // Register form state
  const [regName, setRegName] = useState('');
  const [regUser, setRegUser] = useState('');
  const [regPass, setRegPass] = useState('');
  const [regRole, setRegRole] = useState<'doctor' | 'surgeon' | 'admin'>('surgeon');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const user = await ApiService.login(loginUser, loginPass);
      onLoginSuccess(user);
      setSuccess(`Welcome back, Dr. ${user.username}! Redirecting to Surgical Console...`);
      setTimeout(() => {
        navigate('/console');
      }, 900);
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Verify credentials.');
    } finally {
      setLoading(false);
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);

    if (!regUser.trim() || !regPass.trim()) {
      setError('Username and password are required');
      setLoading(false);
      return;
    }

    try {
      const user = await ApiService.register(regUser, regPass, regRole);
      onLoginSuccess(user);
      setSuccess(`Account registered successfully as ${regRole.toUpperCase()}! Entering Console...`);
      setTimeout(() => {
        navigate('/console');
      }, 900);
    } catch (err: any) {
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickLogin = async (u: string, p: string) => {
    setLoginUser(u);
    setLoginPass(p);
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const user = await ApiService.login(u, p);
      onLoginSuccess(user);
      setSuccess(`Logged in as ${user.username}! Launching Console...`);
      setTimeout(() => {
        navigate('/console');
      }, 800);
    } catch (err: any) {
      setError(err.message || 'Quick login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#a8dcd1] text-[#0f332c] flex flex-col font-sans selection:bg-[#53c0aa] selection:text-[#082923]">
      
      {/* Top Bar */}
      <header className="bg-[#53c0aa] border-b-2 border-[#26685c] px-4 sm:px-8 py-3 select-none shadow-sm">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <button
            onClick={() => navigate('/')}
            className="flex items-center space-x-2 text-xs font-mono font-bold text-[#082923] hover:text-[#175245] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>RETURN TO HOME</span>
          </button>

          <div className="flex items-center space-x-2 cursor-pointer" onClick={() => navigate('/')}>
            <div className="flex items-center justify-center w-7 h-7 rounded bg-[#3fa792] border border-[#26685c] text-[#092b24]">
              <Bot className="w-4 h-4" />
            </div>
            <span className="font-extrabold text-sm text-[#082923] font-mono">ROBOSURGE AUTH</span>
          </div>

          <button
            onClick={() => navigate('/console')}
            className="px-3 py-1 bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] font-mono font-bold text-xs rounded border border-[#26685c] transition-colors"
          >
            GUEST CONSOLE
          </button>
        </div>
      </header>

      {/* Main Form Center Card */}
      <main className="flex-1 flex items-center justify-center p-4 sm:p-6">
        <div className="retro-panel max-w-md w-full p-6 space-y-5 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
          
          {/* Card Header */}
          <div className="text-center space-y-1.5 pb-2 border-b border-[#26685c]/40">
            <div className="w-12 h-12 rounded-xl bg-[#53c0aa] border-2 border-[#26685c] flex items-center justify-center mx-auto text-[#082923] shadow-inner">
              <Shield className="w-6 h-6" />
            </div>
            <h2 className="text-base sm:text-lg font-black font-mono tracking-tight text-[#082923] uppercase">
              Surgeon & Clinical Gateway
            </h2>
            <p className="text-xs text-[#15463c] font-medium">
              Role-Based Access Control (RBAC) & Hardware Authority
            </p>
          </div>

          {/* Already Logged In Banner */}
          {currentUser && (
            <div className="bg-[#b0ded4] p-3.5 rounded-lg border border-[#26685c] space-y-2 text-xs font-mono">
              <div className="flex items-center justify-between text-[#082923]">
                <span className="text-[#20574b]">ACTIVE SESSION:</span>
                <span className="font-extrabold text-[#108e68]">AUTHORIZATION GRANTED</span>
              </div>
              <div className="flex items-center justify-between text-[#082923]">
                <span>DOCTOR: {currentUser.username}</span>
                <span className="px-2 py-0.2 rounded bg-[#53c0aa] border border-[#26685c] font-bold uppercase text-[10px]">
                  {currentUser.role}
                </span>
              </div>
              <div className="flex items-center space-x-2 pt-2 border-t border-[#26685c]/30">
                <button
                  onClick={() => navigate('/console')}
                  className="flex-1 py-1.5 bg-[#53c0aa] hover:bg-[#3fa792] text-[#082923] font-bold text-xs rounded border border-[#26685c] transition-colors flex items-center justify-center space-x-1"
                >
                  <Terminal className="w-3.5 h-3.5" />
                  <span>Enter Console</span>
                </button>
                <button
                  onClick={onLogout}
                  className="px-3 py-1.5 bg-[#d84b4b] hover:bg-[#c93e3e] text-white font-bold text-xs rounded border border-[#8a2222] transition-colors"
                >
                  Sign Out
                </button>
              </div>
            </div>
          )}

          {/* Tab Switcher */}
          {!currentUser && (
            <div className="flex border-b border-[#26685c]/40 text-xs font-mono">
              <button
                onClick={() => { setMode('login'); setError(null); setSuccess(null); }}
                className={`flex-1 pb-2 font-bold transition-colors border-b-2 flex items-center justify-center space-x-1.5 ${
                  mode === 'login'
                    ? 'border-[#26685c] text-[#082923]'
                    : 'border-transparent text-[#20574b] hover:text-[#082923]'
                }`}
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>SIGN IN</span>
              </button>
              <button
                onClick={() => { setMode('register'); setError(null); setSuccess(null); }}
                className={`flex-1 pb-2 font-bold transition-colors border-b-2 flex items-center justify-center space-x-1.5 ${
                  mode === 'register'
                    ? 'border-[#26685c] text-[#082923]'
                    : 'border-transparent text-[#20574b] hover:text-[#082923]'
                }`}
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>REGISTER DOCTOR</span>
              </button>
            </div>
          )}

          {/* Feedback Messages */}
          {error && (
            <div className="p-2.5 rounded bg-[#fecaca] border border-[#dc2626] text-[#991b1b] text-xs font-mono flex items-center space-x-2 font-bold">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="p-2.5 rounded bg-[#bbf7d0] border border-[#16a34a] text-[#166534] text-xs font-mono flex items-center space-x-2 font-bold">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              <span>{success}</span>
            </div>
          )}

          {/* Mode 1: Login Form */}
          {!currentUser && mode === 'login' && (
            <form onSubmit={handleLoginSubmit} className="space-y-3.5">
              <div>
                <label className="text-xs font-mono text-[#082923] font-bold block mb-1">
                  Surgeon / User ID
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={loginUser}
                    onChange={(e) => setLoginUser(e.target.value)}
                    placeholder="Enter ID or username"
                    className="w-full bg-[#d8f5ee] border-2 border-[#26685c] rounded-lg py-2 pl-9 pr-3 text-xs font-mono text-[#082923] placeholder-[#3b7569] outline-none focus:bg-[#e9fbf6] transition-colors"
                  />
                  <User className="w-4 h-4 text-[#20574b] absolute left-3 top-2.5 pointer-events-none" />
                </div>
              </div>

              <div>
                <label className="text-xs font-mono text-[#082923] font-bold block mb-1">
                  Security Passkey
                </label>
                <div className="relative">
                  <input
                    type="password"
                    value={loginPass}
                    onChange={(e) => setLoginPass(e.target.value)}
                    placeholder="Enter password"
                    className="w-full bg-[#d8f5ee] border-2 border-[#26685c] rounded-lg py-2 pl-9 pr-3 text-xs font-mono text-[#082923] placeholder-[#3b7569] outline-none focus:bg-[#e9fbf6] transition-colors"
                  />
                  <Lock className="w-4 h-4 text-[#20574b] absolute left-3 top-2.5 pointer-events-none" />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 bg-[#53c0aa] hover:bg-[#3fa792] disabled:opacity-50 text-[#082923] font-mono font-black text-xs uppercase tracking-wider rounded-lg border-2 border-[#26685c] transition-all shadow"
              >
                {loading ? 'Verifying Credentials...' : 'Authenticate & Enter Console'}
              </button>

              {/* Quick Dev Credentials */}
              <div className="pt-2 border-t border-[#26685c]/40 space-y-1.5">
                <span className="text-[10px] font-mono text-[#20574b] uppercase font-bold block">
                  Quick Demo Accounts:
                </span>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleQuickLogin('admin', 'admin123')}
                    className="p-1.5 bg-[#b0ded4] hover:bg-[#53c0aa] text-left text-[11px] font-mono rounded border border-[#26685c] text-[#082923] transition-colors"
                  >
                    <span className="font-bold block">Admin Doctor</span>
                    <span className="text-[10px] text-[#20574b]">admin / admin123</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleQuickLogin('doctor', 'doctor123')}
                    className="p-1.5 bg-[#b0ded4] hover:bg-[#53c0aa] text-left text-[11px] font-mono rounded border border-[#26685c] text-[#082923] transition-colors"
                  >
                    <span className="font-bold block">Attending Surgeon</span>
                    <span className="text-[10px] text-[#20574b]">doctor / doctor123</span>
                  </button>
                </div>
              </div>
            </form>
          )}

          {/* Mode 2: Register Form */}
          {!currentUser && mode === 'register' && (
            <form onSubmit={handleRegisterSubmit} className="space-y-3">
              <div>
                <label className="text-xs font-mono text-[#082923] font-bold block mb-1">
                  Full Clinical Name
                </label>
                <input
                  type="text"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  placeholder="Dr. Jane Doe, MD"
                  className="w-full bg-[#d8f5ee] border-2 border-[#26685c] rounded-lg py-1.5 px-3 text-xs font-mono text-[#082923] outline-none focus:bg-[#e9fbf6]"
                />
              </div>

              <div>
                <label className="text-xs font-mono text-[#082923] font-bold block mb-1">
                  Username ID
                </label>
                <input
                  type="text"
                  value={regUser}
                  onChange={(e) => setRegUser(e.target.value)}
                  placeholder="e.g. jdoe_surgeon"
                  className="w-full bg-[#d8f5ee] border-2 border-[#26685c] rounded-lg py-1.5 px-3 text-xs font-mono text-[#082923] outline-none focus:bg-[#e9fbf6]"
                />
              </div>

              <div>
                <label className="text-xs font-mono text-[#082923] font-bold block mb-1">
                  Password
                </label>
                <input
                  type="password"
                  value={regPass}
                  onChange={(e) => setRegPass(e.target.value)}
                  placeholder="Min 6 characters"
                  className="w-full bg-[#d8f5ee] border-2 border-[#26685c] rounded-lg py-1.5 px-3 text-xs font-mono text-[#082923] outline-none focus:bg-[#e9fbf6]"
                />
              </div>

              <div>
                <label className="text-xs font-mono text-[#082923] font-bold block mb-1">
                  Clinical Role
                </label>
                <select
                  value={regRole}
                  onChange={(e: any) => setRegRole(e.target.value)}
                  className="w-full bg-[#d8f5ee] border-2 border-[#26685c] rounded-lg py-1.5 px-3 text-xs font-mono text-[#082923] outline-none focus:bg-[#e9fbf6]"
                >
                  <option value="surgeon">Lead Robotic Surgeon</option>
                  <option value="doctor">Attending Physician</option>
                  <option value="admin">Biomedical Systems Admin</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 bg-[#53c0aa] hover:bg-[#3fa792] disabled:opacity-50 text-[#082923] font-mono font-black text-xs uppercase tracking-wider rounded-lg border-2 border-[#26685c] transition-all shadow mt-2"
              >
                {loading ? 'Creating Doctor Account...' : 'Complete Registration'}
              </button>
            </form>
          )}

          {/* Bottom Security Footer Note */}
          <div className="text-[10px] font-mono text-[#20574b] text-center pt-2 border-t border-[#26685c]/30">
            <span>256-Bit Encrypted JWT Handshake • Hardware E-STOP Active</span>
          </div>
        </div>
      </main>
    </div>
  );
};
