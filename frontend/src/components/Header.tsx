import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Activity, 
  Camera, 
  Radio, 
  Sliders, 
  ShieldAlert, 
  Sparkles,
  User,
  Power,
  Settings,
  Bot
} from 'lucide-react';
import { SystemVitals, UserAuth } from '../types/robosurge';
import { ApiService } from '../services/api';

interface HeaderProps {
  vitals: SystemVitals;
  user: UserAuth | null;
  onOpenCalibration: () => void;
  onOpenLogin: () => void;
  onRefresh: () => void;
  onAbortSuccess: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  vitals,
  user,
  onOpenCalibration,
  onOpenLogin,
  onAbortSuccess,
}) => {
  const navigate = useNavigate();
  const [aborting, setAborting] = useState(false);
  const [showAbortConfirm, setShowAbortConfirm] = useState(false);
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toTimeString().split(' ')[0]);
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleAbort = async () => {
    setAborting(true);
    try {
      await ApiService.abort(false);
      onAbortSuccess();
      setShowAbortConfirm(false);
    } catch (e: any) {
      alert(`Abort error: ${e.message}`);
    } finally {
      setAborting(false);
    }
  };

  const isOnline = vitals.camera !== 'OFFLINE' || vitals.serial !== 'OFFLINE';

  return (
    <header className="bg-[#53c0aa] border-b-2 border-[#26685c] px-3 sm:px-5 py-2 shadow-md select-none sticky top-0 z-40">
      <div className="max-w-[1920px] mx-auto flex flex-wrap items-center justify-between gap-2.5">
        
        {/* Brand Logo & Title (clickable to return home) */}
        <div 
          onClick={() => navigate('/')}
          className="flex items-center space-x-2.5 cursor-pointer group"
          title="Return to Landing Page"
        >
          <div className="flex items-center justify-center w-7 h-7 rounded-sm bg-[#3fa792] border border-[#26685c] shadow-inner text-[#092b24] group-hover:bg-[#349480] transition-colors">
            <Bot className="w-4 h-4" />
          </div>
          <div className="flex items-baseline space-x-2">
            <h1 className="font-black tracking-wider text-sm sm:text-base text-[#082923] font-mono">
              ROBOSURGE
            </h1>
            <span className="text-[10px] sm:text-[11px] font-mono tracking-widest text-[#15463c] uppercase font-bold">
              SURGEON CONSOLE
            </span>
          </div>
        </div>

        {/* Center: System Vitals Badges */}
        <div className="flex flex-wrap items-center gap-1.5 text-xs font-mono">
          {/* Camera Status */}
          <div className="flex items-center space-x-1 px-2.5 py-0.5 rounded-sm bg-[#c0eae1] border border-[#26685c] text-[#092b24] shadow-sm">
            <Camera className="w-3.5 h-3.5 text-[#1b5b4e]" />
            <span className="text-[#20574b] font-sans font-medium text-[11px]">CAM:</span>
            <span className="font-extrabold text-[11px]">{vitals.camera}</span>
          </div>

          {/* Serial Status */}
          <div className="flex items-center space-x-1 px-2.5 py-0.5 rounded-sm bg-[#c0eae1] border border-[#26685c] text-[#092b24] shadow-sm">
            <Radio className="w-3.5 h-3.5 text-[#1b5b4e]" />
            <span className="text-[#20574b] font-sans font-medium text-[11px]">ESP32:</span>
            <span className="font-extrabold text-[11px]">{vitals.serial}</span>
          </div>

          {/* Groq AI Status */}
          <div className="flex items-center space-x-1 px-2.5 py-0.5 rounded-sm bg-[#c0eae1] border border-[#26685c] text-[#092b24] shadow-sm">
            <Sparkles className="w-3.5 h-3.5 text-[#1b5b4e]" />
            <span className="text-[#20574b] font-sans font-medium text-[11px]">AGENT:</span>
            <span className="font-extrabold text-[11px]">{vitals.groq}</span>
          </div>
        </div>

        {/* Right Status, Tools & Actions */}
        <div className="flex items-center space-x-2">
          {/* System Online Badge */}
          <div className="flex items-center space-x-1.5 text-xs font-mono font-bold text-[#092b24]">
            <span className="w-2 h-2 rounded-full bg-[#084b3e] animate-ping" />
            <span className="uppercase tracking-wide text-[11px]">{isOnline ? 'ONLINE' : 'STANDBY'}</span>
          </div>

          {/* UTC Clock */}
          <div className="hidden sm:block text-xs font-mono text-[#15463c] font-medium px-1.5 text-[11px]">
            UTC {timeStr}
          </div>

          {/* Calibrate / Settings Button */}
          <button
            onClick={onOpenCalibration}
            className="p-1.5 rounded-sm bg-[#c0eae1] hover:bg-[#b0ded4] active:scale-95 border border-[#26685c] text-[#092b24] transition-all shadow-sm"
            title="Calibrate Robot & Tool"
          >
            <Settings className="w-3.5 h-3.5" />
          </button>

          {/* Doctor Auth Button */}
          <button
            onClick={onOpenLogin}
            className="px-2.5 py-1 rounded-sm bg-[#c0eae1] hover:bg-[#b0ded4] active:scale-95 border border-[#26685c] text-[#092b24] transition-all flex items-center space-x-1.5 text-xs font-mono font-bold shadow-sm"
            title="Doctor Login"
          >
            <User className="w-3.5 h-3.5 text-[#1b5b4e]" />
            <span className="text-[11px]">{user ? user.username : 'DOCTOR'}</span>
          </button>

          {/* E-STOP Button */}
          <button
            onClick={() => setShowAbortConfirm(true)}
            className="flex items-center space-x-1 px-3 py-1 rounded-sm bg-[#d84b4b] hover:bg-[#c93e3e] active:scale-95 text-white font-black text-[11px] font-mono tracking-wider uppercase transition-all shadow border border-[#8a2222]"
          >
            <ShieldAlert className="w-3.5 h-3.5" />
            <span>E-STOP</span>
          </button>
        </div>
      </div>

      {/* Emergency Stop Confirmation Modal */}
      {showAbortConfirm && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#c0eae1] border-2 border-[#8a2222] rounded-sm max-w-md w-full p-5 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center space-x-2.5 text-[#8a2222] mb-2.5">
              <ShieldAlert className="w-5 h-5" />
              <h3 className="text-sm font-bold uppercase tracking-wider font-mono">
                Confirm Emergency Stop
              </h3>
            </div>
            <p className="text-[#15463c] text-xs mb-4 leading-relaxed">
              This will immediately send the <strong>ABORT</strong> command to the motion executor, cutting robot arm actuation and halting all active trajectory steps.
            </p>
            <div className="flex items-center justify-end space-x-2">
              <button
                onClick={() => setShowAbortConfirm(false)}
                className="px-3 py-1 rounded-sm text-xs font-bold text-[#15463c] bg-[#a8dcd1] hover:bg-[#97cfc3] border border-[#26685c] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAbort}
                disabled={aborting}
                className="px-3.5 py-1 rounded-sm text-xs font-bold text-white bg-[#d84b4b] hover:bg-[#c93e3e] transition-all flex items-center space-x-1.5 border border-[#8a2222]"
              >
                <Power className="w-3.5 h-3.5" />
                <span>{aborting ? 'Aborting...' : 'Halt Motion Now'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};
