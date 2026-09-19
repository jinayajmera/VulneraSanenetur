import React, { useState } from 'react';
import { User, Lock, X, Shield, AlertCircle } from 'lucide-react';
import { ApiService } from '../services/api';
import { UserAuth } from '../types/robosurge';

interface LoginModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: UserAuth | null;
  onLoginSuccess: (user: UserAuth) => void;
  onLogout: () => void;
}

export const LoginModal: React.FC<LoginModalProps> = ({
  isOpen,
  onClose,
  currentUser,
  onLoginSuccess,
  onLogout,
}) => {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await ApiService.login(username, password);
      onLoginSuccess(user);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickLogin = async (u: string, p: string) => {
    setUsername(u);
    setPassword(p);
    setLoading(true);
    setError(null);
    try {
      const user = await ApiService.login(u, p);
      onLoginSuccess(user);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 select-none">
      <div className="bg-[#c0eae1] border-2 border-[#26685c] rounded-sm max-w-md w-full p-4 shadow-2xl animate-in fade-in zoom-in-95 duration-150 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#26685c]/40 pb-2">
          <div className="flex items-center space-x-2 text-[#082923]">
            <Shield className="w-4 h-4 text-[#1b5b4e]" />
            <h3 className="text-xs sm:text-sm font-extrabold uppercase font-mono tracking-wider">
              Surgeon Authorization
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-sm text-[#20574b] hover:text-[#082923] hover:bg-[#b0ded4] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {error && (
          <div className="p-2 rounded-sm bg-[#fecaca] border border-[#dc2626] text-[#991b1b] text-xs font-mono flex items-center space-x-2 font-bold">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {currentUser ? (
          <div className="space-y-2.5">
            <div className="bg-[#b0ded4] p-2.5 rounded-sm border border-[#26685c] space-y-1 text-xs font-mono text-[#082923]">
              <div className="flex justify-between">
                <span className="text-[#20574b]">Logged in as:</span>
                <span className="font-bold">{currentUser.username}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#20574b]">Role:</span>
                <span className="font-bold uppercase text-[#1b5b4e]">{currentUser.role}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#20574b]">Status:</span>
                <span className="font-bold text-[#108e68]">Authorized</span>
              </div>
            </div>

            <div className="flex justify-end space-x-2">
              <button
                onClick={onLogout}
                className="px-3 py-1 bg-[#d84b4b] hover:bg-[#c93e3e] text-white font-bold text-xs font-mono rounded-sm border border-[#8a2222] transition-colors"
              >
                Sign Out
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleLogin} className="space-y-2">
            <div>
              <label className="text-xs font-mono text-[#082923] font-bold block mb-0.5">
                Username
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1.5 pl-7 text-xs font-mono text-[#082923] outline-none"
                />
                <User className="w-3.5 h-3.5 text-[#20574b] absolute left-2 top-2 pointer-events-none" />
              </div>
            </div>

            <div>
              <label className="text-xs font-mono text-[#082923] font-bold block mb-0.5">
                Password
              </label>
              <div className="relative">
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1.5 pl-7 text-xs font-mono text-[#082923] outline-none"
                />
                <Lock className="w-3.5 h-3.5 text-[#20574b] absolute left-2 top-2 pointer-events-none" />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-1.5 bg-[#53c0aa] hover:bg-[#3fa792] disabled:opacity-50 text-[#082923] font-bold text-xs font-mono rounded-sm border border-[#26685c] transition-colors mt-1"
            >
              {loading ? 'Authenticating...' : 'Sign In'}
            </button>

            {/* Quick Login Chips */}
            <div className="pt-2 border-t border-[#26685c]/40 space-y-1">
              <span className="text-[10px] font-mono text-[#20574b] uppercase block font-bold">
                Quick Dev Credentials:
              </span>
              <button
                type="button"
                onClick={() => handleQuickLogin('admin', 'admin123')}
                className="w-full py-0.5 px-2 bg-[#b0ded4] hover:bg-[#53c0aa] text-xs font-mono text-[#082923] rounded-sm border border-[#26685c] text-left flex justify-between"
              >
                <span>Admin Doctor</span>
                <span className="font-bold">admin / admin123</span>
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
